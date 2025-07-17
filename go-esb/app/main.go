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

func publishCheckoutReady(ch *amqp.Channel, body []byte) {
	err := ch.Publish(
		"marketplace",
		"checkout.ready",
		false,
		false,
		amqp.Publishing{
			ContentType: "application/json",
			Body:        body,
		},
	)

	log.Printf("Публикация сообщения checkout.ready: %s\n", string(body))

	failOnError("Ошибка публикации сообщения checkout.ready:", err)
}

func handleOrderCreated(ch *amqp.Channel, body []byte) {
	type Order struct {
		OrderID    int `json:"order_id"`
		TotalPrice int `json:"total_price"`
	}
	var order Order
	err := json.Unmarshal(body, &order)
	failOnError("Ошибка декодирования JSON:", err)

	checkoutReadyMsg, err := json.Marshal(order)
	failOnError("Ошибка кодирования JSON:", err)

	publishCheckoutReady(ch, checkoutReadyMsg)
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
		false,         // durable
		false,         // delete when unused
		false,         // exclusive
		false,         // no-wait
		nil,           // аргументы
	)
	failOnError("Ошибка создания exchange:", err)

	q, err := ch.QueueDeclare(
		"ebs_queue", // имя очереди
		true,        // durable
		false,
		false,
		false,
		nil,
	)
	failOnError("Ошибка создания очереди:", err)

	routingKeys := []string{
		"order.created",
		"payment.success",
		"delivery.sent",
	}

	for key := range routingKeys {
		err = ch.QueueBind(
			q.Name,           // имя очереди
			routingKeys[key], // routing key
			"marketplace",    // имя exchange
			false,
			nil,
		)
		failOnError(fmt.Sprintf("Ошибка привязки очереди к exchange с ключом %s:", routingKeys[key]), err)
	}

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

	log.Printf("go-esb запущен.")

	for msg := range msgs {
		switch msg.RoutingKey {
		case "order.created":
			handleOrderCreated(ch, msg.Body)
		default:
			log.Panicf("Неизвестный routing key: %s", msg.RoutingKey)
		}
	}

}
