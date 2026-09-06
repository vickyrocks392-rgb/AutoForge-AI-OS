package main

import (
	"encoding/json"
	"fmt"
	"net/http"
)

type Account struct {
	AccountID     string  `json:"accountId"`
	AccountNumber string  `json:"accountNumber"`
	Balance       float64 `json:"balance"`
	Status        string  `json:"status"`
}

func accountHandler(w http.ResponseWriter, r *http.Request) {
	acc := Account{
		AccountID:     "ACC-001",
		AccountNumber: "9988776655",
		Balance:       3500.25,
		Status:        "ACTIVE",
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(acc)
}

func main() {
	http.HandleFunc("/api/v1/accounts/sample", accountHandler)
	fmt.Println("AutoForge Go Service Initialized")
}
