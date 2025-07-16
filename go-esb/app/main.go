package main

import (
	"fmt"

	"github.com/streadway/amqp"
)

func main() {
	conn, err := amqp.Dial("amqp://rmq_admin:rmq_password@localhost/")

	if err != nil {
		fmt.Println("Ошибка подключения к RabbitMQ:", err)
		return
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		fmt.Println("Ошибка создания канала:", err)
		return
	}
	defer ch.Close()

	err = ch.ExchangeDeclare(
		"events",
		"topic",
		false, // durable
		false, // delete when unused
		false, // exclusive
		false, // no-wait
		nil,   // аргументы
	)
	if err != nil {
		fmt.Println("Ошибка создания обмена:", err)
		return
	}

	q, err := ch.QueueDeclare(
		"order_events_queue", // имя очереди
		true,                 // durable
		false,                // delete when unused
		false,                // exclusive
		false, nil,
	)
	if err != nil {
		fmt.Println("Ошибка создания очереди:", err)
		return
	}

	err = ch.QueueBind(
		q.Name,          // имя очереди
		"order.created", // routing key
		"events",        // имя exchange
		false,
		nil,
	)
	if err != nil {
		fmt.Println("Ошибка привязки очереди к exchange:", err)
		return
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
	if err != nil {
		fmt.Println("Ошибка получения сообщений:", err)
		return
	}

	for msg := range msgs {
		fmt.Printf("Получено сообщение: %s\n", msg.Body)
	}
}
