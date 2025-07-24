package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"

	"github.com/streadway/amqp"
)

func failOnError(msg string, err error) {
	if err != nil {
		log.Panicf("%s: %s\n", msg, err)
	}
}

func handleNotificationsAction(body []byte) {
	type NotificationActionInput struct {
		OrderID     int    `json:"order_id"`
		Sub         string `json:"sub"`
		Description string `json:"description"`
	}

	var inputNotification NotificationActionInput
	err := json.Unmarshal(body, &inputNotification)
	failOnError("Ошибка декодирования JSON:", err)

	log.Printf("Получено уведомление для заказа %d: %s - %s\n", inputNotification.OrderID, inputNotification.Sub, inputNotification.Description)
}

func worker(tasks <-chan amqp.Delivery) {
	for msg := range tasks {
		handleNotificationsAction(msg.Body)
	}
}

func main() {
	RABBITMQ_URL := os.Getenv("RABBITMQ_URL")

	conn, err := amqp.Dial(RABBITMQ_URL)
	failOnError(fmt.Sprintf("Ошибка подключения к RabbitMQ (%s):", RABBITMQ_URL), err)
	defer conn.Close()

	ch, err := conn.Channel()
	failOnError("Ошибка открытия канала:", err)
	defer ch.Close()

	err = ch.ExchangeDeclare(
		"marketplace", // имя exchange
		"direct",      // тип exchange
		true,          // durable
		false,         // delete when unused
		false,         // exclusive
		false,         // no-wait
		nil,           // аргументы
	)
	failOnError("Ошибка создания exchange:", err)

	q, err := ch.QueueDeclare(
		"notifications_queue", // имя очереди
		true,                  // durable
		false,
		false,
		false,
		nil,
	)
	failOnError("Ошибка создания очереди:", err)

	err = ch.QueueBind(
		q.Name,                // имя очереди
		"notification.action", // routing key
		"marketplace",         // имя exchange
		false,
		nil,
	)
	failOnError("Ошибка привязки очереди к exchange:", err)

	msgs, err := ch.Consume(
		q.Name, // имя очереди
		"",     // consumer tag
		true,   // auto-acknowledge
		false,  // exclusive
		false,  // no-local
		false,  // no-wait
		nil,    // аргументы
	)
	failOnError("Ошибка подписки на очередь:", err)

	log.Printf("notification-service запущен.")

	workerCount := 10

	tasks := make(chan amqp.Delivery, 100)

	for i := 0; i < workerCount; i++ {
		go worker(tasks)
	}

	for msg := range msgs {
		tasks <- msg
	}
}
