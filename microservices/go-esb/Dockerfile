FROM golang:1.22.2 AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o go-esb ./app

FROM alpine:3.19

WORKDIR /app
COPY --from=builder /app/go-esb .

CMD ["./go-esb"]
