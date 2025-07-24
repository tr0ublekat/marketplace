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

func publishMessage(ch *amqp.Channel, routingKey string, body []byte) {
	err := ch.Publish(
		"marketplace",
		routingKey,
		false,
		false,
		amqp.Publishing{
			ContentType: "application/json",
			Body:        body,
		},
	)

	failOnError(fmt.Sprintf("Ошибка публикации сообщения с routing key %s:", routingKey), err)

	log.Printf("Публикация сообщения %s: %s\n", routingKey, string(body))
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

	publishMessage(ch, "checkout.ready", checkoutReadyMsg)
	sendNotification(ch, order.OrderID, "order", fmt.Sprintf("Заказ успешно создан с общей стоимостью %d", order.TotalPrice))
}

func handleDeliverySend(ch *amqp.Channel, order_id int) {
	type Delivery struct {
		OrderID int `json:"order_id"`
	}

	delivery := Delivery{OrderID: order_id}
	deliveryMsg, err := json.Marshal(delivery)
	failOnError("Ошибка кодирования JSON:", err)

	publishMessage(ch, "delivery.send", deliveryMsg)
}

func handlePaymentDiscard(body []byte) {
	log.Panicf("Платеж не прошел: %s\n", string(body))
}

func handlePaymentCheck(ch *amqp.Channel, body []byte) {
	type Payment struct {
		OrderID    int  `json:"order_id"`
		TotalPrice int  `json:"total_price"`
		IsSuccess  bool `json:"is_success"`
	}

	var payment Payment
	err := json.Unmarshal(body, &payment)
	failOnError("Ошибка декодирования JSON:", err)

	if payment.IsSuccess {
		handleDeliverySend(ch, payment.OrderID)
		sendNotification(ch, payment.OrderID, "payment", fmt.Sprintf("Платеж успешно прошел на сумму %d", payment.TotalPrice))
	} else {
		handlePaymentDiscard(body)
		sendNotification(ch, payment.OrderID, "payment", "Платеж не прошел")
	}
}

func handleDeliveryGetStatus(ch *amqp.Channel, body []byte) {
	type DeliveryStatus struct {
		OrderID int    `json:"order_id"`
		Status  string `json:"status"`
	}

	var deliveryStatus DeliveryStatus
	err := json.Unmarshal(body, &deliveryStatus)
	failOnError("Ошибка декодирования JSON:", err)

	sendNotification(ch, deliveryStatus.OrderID, "delivery", fmt.Sprintf("Обновлен статус доставки: %s", deliveryStatus.Status))
}

func sendNotification(ch *amqp.Channel, orderID int, sub string, description string) {
	type Notification struct {
		OrderID     int    `json:"order_id"`
		Sub         string `json:"sub"`
		Description string `json:"description"`
	}

	notification := Notification{
		OrderID:     orderID,
		Sub:         sub,
		Description: description,
	}

	notificationMsg, err := json.Marshal(notification)
	failOnError("Ошибка кодирования JSON:", err)

	publishMessage(ch, "notification.action", notificationMsg)
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
		"payment.action",
		"delivery.action",
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
		go func(msg amqp.Delivery) {
			switch msg.RoutingKey {
			case "order.created":
				handleOrderCreated(ch, msg.Body)
			case "payment.action":
				handlePaymentCheck(ch, msg.Body)
			case "delivery.action":
				handleDeliveryGetStatus(ch, msg.Body)
			default:
				log.Panicf("Неизвестный routing key: %s", msg.RoutingKey)
			}
		}(msg)
	}
}
