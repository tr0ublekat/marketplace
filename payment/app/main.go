package main

import (
	"encoding/json"
	"log"
	"math/rand"
	"os"

	"github.com/streadway/amqp"
)

func failOnError(msg string, err error) {
	if err != nil {
		log.Panicf("%s: %s\n", msg, err)
	}
}

func publishPaymentAction(ch *amqp.Channel, body []byte) {
	err := ch.Publish(
		"marketplace",
		"payment.action",
		false,
		false,
		amqp.Publishing{
			ContentType: "application/json",
			Body:        body,
		},
	)
	failOnError("Ошибка публикации сообщения:", err)

	log.Printf("Публикация сообщения payment.action: %s\n", string(body))
}

func mockGetPaymentStatus() bool {
	return (rand.Intn(100) >= 2)
}

func handlePaymentAction(ch *amqp.Channel, body []byte) {

	type PaymentActionInput struct {
		OrderID    int `json:"order_id"`
		TotalPrice int `json:"total_price"`
	}

	type PaymentActionOutput struct {
		OrderID    int  `json:"order_id"`
		TotalPrice int  `json:"total_price"`
		IsSuccess  bool `json:"is_success"`
	}

	var inputAction PaymentActionInput
	err := json.Unmarshal(body, &inputAction)
	failOnError("Ошибка декодирования JSON:", err)

	isSuccess := mockGetPaymentStatus()
	log.Printf("Платеж для заказа %d на сумму %d: %t\n", inputAction.OrderID, inputAction.TotalPrice, isSuccess)

	var outputAction PaymentActionOutput
	outputAction.OrderID = inputAction.OrderID
	outputAction.TotalPrice = inputAction.TotalPrice
	outputAction.IsSuccess = isSuccess

	actionMsg, err := json.Marshal(outputAction)
	failOnError("Ошибка кодирования JSON:", err)

	publishPaymentAction(ch, actionMsg)
}

func main() {
	RABBITMQ_URL := os.Getenv("RABBITMQ_URL")

	conn, err := amqp.Dial(RABBITMQ_URL)
	failOnError("Ошибка подключения к RabbitMQ:", err)
	defer conn.Close()

	ch, err := conn.Channel()
	failOnError("Ошибка открытия канала:", err)
	defer ch.Close()

	err = ch.ExchangeDeclare(
		"marketplace", // name
		"direct",      // type
		true,          // durable
		false,         // auto-deleted
		false,         // internal
		false,         // no-wait
		nil,           // arguments
	)
	failOnError("Ошибка объявления exchange:", err)

	q, err := ch.QueueDeclare(
		"payments_queue", // name
		true,             // durable
		false,            // auto-deleted
		false,            // exclusive
		false,            // no-wait
		nil,              // arguments
	)
	failOnError("Ошибка объявления очереди orders:", err)

	err = ch.QueueBind(
		q.Name,           // queue name
		"checkout.ready", // routing key
		"marketplace",    // exchange
		false,            // no-wait
		nil,              // arguments
	)
	failOnError("Ошибка привязки очереди к exchange:", err)

	log.Printf("payment-service запущен.")

	msgs, err := ch.Consume(
		q.Name, // queue name
		"",     // consumer tag
		true,   // auto-acknowledge
		false,  // exclusive
		false,  // no-local
		false,  // no-wait
		nil,    // arguments
	)
	failOnError("Ошибка подписки на очередь:", err)

	for msg := range msgs {
		handlePaymentAction(ch, msg.Body)
	}
}
