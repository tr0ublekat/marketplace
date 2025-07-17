package main

import (
	"fmt"

	"github.com/streadway/amqp"
)

func failOnError(msg string, err error) {
	if err != nil {
		fmt.Printf("%s: %s\n", msg, err)
	}
}

func handleOrderCreated(body []byte) {
	fmt.Printf("Заказ создан: %s\n", string(body))
}

func main() {
	conn, err := amqp.Dial("amqp://rmq_admin:rmq_password@localhost/")
	failOnError("Ошибка подключения к RabbitMQ:", err)
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

	fmt.Println("go-esb успешно запущен.")

	for msg := range msgs {
		switch msg.RoutingKey {
		case "order.created":
			handleOrderCreated(msg.Body)
		default:
			fmt.Printf("Неизвестное сообщение: %s\n", msg.RoutingKey)
		}
	}

}
