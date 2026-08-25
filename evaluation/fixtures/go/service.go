package service

import "fmt"

func ProcessData(data string) string {
    return fmt.Sprintf("Processed: %s", data)
}

func ExecuteTask(val string) string {
    return ProcessData(val)
}
