export function formatOrderSummary(orderId: string): string {
    return `Order: ${orderId}`;
}

export function validateOrder(order: { id: string; amount: number }): boolean {
    return order.amount > 0;
}
