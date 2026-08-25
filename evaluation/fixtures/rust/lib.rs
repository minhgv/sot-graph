/* outer /* nested */ fn target() {} */
pub const RAW_PATTERN: &str = r#"fn target() {}"#;

pub fn compute(a: i32, b: i32) -> i32 {
    a + b
}

pub fn execute_operation(x: i32) -> i32 {
    compute(x, 100)
}
