## Testing Best Practices

### Test Organization

Group related tests in modules:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    mod entity_tests {
        use super::*;

        #[gpui::test]
        fn test_creation() { /* ... */ }

        #[gpui::test]
        fn test_updates() { /* ... */ }
    }

    mod async_tests {
        use super::*;

        #[gpui::test]
        async fn test_async_ops() { /* ... */ }
    }

    mod distributed_tests {
        use super::*;

        #[gpui::test]
        fn test_multi_app() { /* ... */ }
    }
}
```

### Setup and Teardown

Use helper functions for common setup:

```rust
fn create_test_counter(cx: &mut TestAppContext) -> Entity<Counter> {
    cx.new(|cx| Counter::new(cx))
}

#[gpui::test]
fn test_counter_operations(cx: &mut TestAppContext) {
    let counter = create_test_counter(cx);

    // Test operations
}
```

### Assertions

Use descriptive assertions:

```rust
#[gpui::test]
fn test_counter_bounds(cx: &mut TestAppContext) {
    let counter = create_test_counter(cx);

    // Test upper bound
    for _ in 0..100 {
        counter.update(cx, |counter, cx| {
            counter.increment(cx);
        });
    }

    let count = counter.read_with(cx, |counter, _| counter.count);
    assert!(count <= 100, "Counter should not exceed maximum");

    // Test lower bound
    for _ in 0..200 {
        counter.update(cx, |counter, cx| {
            counter.decrement(cx);
        });
    }

    let count = counter.read_with(cx, |counter, _| counter.count);
    assert!(count >= 0, "Counter should not go below minimum");
}
```

### Performance Testing

Keep wall-clock benchmarks separate from deterministic state tests. A fixed
100 ms assertion inside `#[gpui::test]` is sensitive to machine load and does not
measure native rendering performance. Use the consumer project's benchmark or
profiling tools, record the build mode and workload, and compare against a stated
baseline. Test observable limits such as bounded work or item counts separately
when those are part of the component contract.

## Running Tests

### Basic Test Execution

```bash
# Run all tests
cargo test

# Run specific test
cargo test test_counter_operations

# Run tests in a specific module
cargo test entity_tests::

# Run with output
cargo test -- --nocapture
```

### Test Configuration

Enable test-support feature for GPUI tests:

```toml
[features]
test-support = ["gpui/test-support"]
```

```bash
cargo test --features test-support
```

### Advanced Test Execution

```bash
# Run Rust tests serially (this does not set GPUI iteration count)
cargo test -- --test-threads=1

# Run tests matching a pattern
cargo test test_async

# Run tests with backtrace on failure
RUST_BACKTRACE=1 cargo test
```

Set repeated GPUI runs with `#[gpui::test(iterations = 10)]` as shown in
[test.md](test.md#property-test-with-iterations). Verify any seed or iteration
environment overrides against the pinned test runner.

### CI integration

Use the consumer project's supported OS, Rust toolchain, and native dependencies.
Run the headless suite with `cargo test --features test-support`; reserve visible
app and native input checks for an environment with a display session. Headless
input dispatch exercises GPUI routing but does not prove AppKit, Windows, or
Wayland/X11 behavior.
