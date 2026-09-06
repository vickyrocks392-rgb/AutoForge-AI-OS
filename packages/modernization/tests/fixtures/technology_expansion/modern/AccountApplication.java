package com.autoforge.account;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class AccountApplication {

    public static void main(String[] args) {
        SpringApplication.run(AccountApplication.class, args);
    }

    @GetMapping("/api/v1/accounts/{id}")
    public CustomerAccount getAccount(@PathVariable String id) {
        return new CustomerAccount(id, "CUST-01", 1500.0, "ACTIVE");
    }
}
