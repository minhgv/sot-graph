package com.example;

public class PaymentService {
    // Text block with fake method
    private String textBlock = """
        public void processPayment() {
        }
        """;

    public boolean validateCard(String card) {
        return card != null && !card.isEmpty();
    }

    public boolean process(String card) {
        return validateCard(card);
    }
}
