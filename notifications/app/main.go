package main

import (
	"encoding/json"
	"fmt"
	"log"

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

func main() {
	RABBITMQ_URL := "amqp://rmq_admin:rmq_password@localhost:5672/"

	conn, err := amqp.Dial(RABBITMQ_URL)
	failOnError(fmt.Sprintf("Ошибка подключения к RabbitMQ (%s):", RABBITMQ_URL), err)
	defer conn.Close()

	ch, err := conn.Channel()
	failOnError("Ошибка открытия канала:", err)
	defer ch.Close()

	err = ch.ExchangeDeclare(
		"marketplace", // имя exchange
		"direct",      // тип exchange
		false,         // durable
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

	for msg := range msgs {
		handleNotificationsAction(msg.Body)
	}
}
