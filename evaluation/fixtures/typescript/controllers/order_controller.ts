import { validateOrder } from "../models/order";

export class OrderController {
    // Exact span adversarial checks
    // function target() {}
    private regexPattern = /function validateOrder/;
    private stringPattern = "function validateOrder() {}";

    public handleOrder(order: { id: string; amount: number }): boolean {
        if (!validateOrder(order)) {
            return false;
        }
        return true;
    }
}
