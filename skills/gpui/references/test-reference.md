# Test Reference

**Contents:** [Testing Patterns](#testing-patterns) · [Testing Crash-Free State Management (Re-entrancy)](#testing-crash-free-state-management-re-entrancy) · [Property Testing](#property-testing) · [Distributed Systems Testing](#distributed-systems-testing) · [Mocking and Isolation](#mocking-and-isolation)

## Testing Patterns

The basic entity, event, async, timer, and deferred-update examples below are
self-contained test modules. The source repository's `validation/gpui/check.py`
extracts and executes these marked examples against Zed revision
`4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e`. Other examples that use application
types are sketches to adapt to the consumer project.

### Basic Entity Testing

Test entity creation, updates, and reads:

<!-- gpui-check: entity-test -->
```rust
use gpui::{AppContext, TestAppContext};

#[derive(Default)]
struct Counter {
    count: i32,
}

#[gpui::test]
fn test_counter_entity(cx: &mut TestAppContext) {
    let counter = cx.new(|_| Counter::default());

    // Test initial state
    let initial_count = counter.read_with(cx, |counter, _| counter.count);
    assert_eq!(initial_count, 0);

    // Test updates
    counter.update(cx, |counter, cx| {
        counter.count = 42;
        cx.notify();
    });

    let updated_count = counter.read_with(cx, |counter, _| counter.count);
    assert_eq!(updated_count, 42);
}
```

### Event Testing

Keep the subscription alive: dropping it immediately removes the callback. This
example detaches it for the entity's lifetime; store it when it needs an explicit
unsubscribe point.

<!-- gpui-check: event-test -->
```rust
use gpui::{AppContext, Context, EventEmitter, TestAppContext};

#[derive(Default)]
struct MyComponent {
    received_value: i32,
}

#[derive(Clone)]
struct ValueChanged {
    new_value: i32,
}

impl EventEmitter<ValueChanged> for MyComponent {}

#[gpui::test]
fn test_event_emission(cx: &mut TestAppContext) {
    let component = cx.new(|cx: &mut Context<MyComponent>| {
        cx.subscribe_self(|this, event: &ValueChanged, cx| {
            this.received_value = event.new_value;
            cx.notify();
        }).detach();

        MyComponent::default()
    });

    // Emit event
    component.update(cx, |_, cx| {
        cx.emit(ValueChanged { new_value: 123 });
    });

    // Verify event was handled
    let received = component.read_with(cx, |comp, _| comp.received_value);
    assert_eq!(received, 123);
}
```

### Action Testing

This sketch assumes `MyComponent` implements `Render`, tracks its `focus_handle`,
and registers an `Increment` action listener that updates `count`. Dispatch through
the window's focus tree rather than calling the handler directly.

```rust
actions!(my_app, [Increment, Decrement]);

#[gpui::test]
fn test_action_dispatch(cx: &mut TestAppContext) {
    let window = cx.update(|cx| {
        cx.open_window(Default::default(), |_, cx| {
            cx.new(|cx| MyComponent::new(cx))
        }).unwrap()
    });

    let mut cx = VisualTestContext::from_window(window.into(), cx);
    let counter = window.root(&mut cx).unwrap();

    // Dispatch action via focus handle
    let focus_handle = counter.read_with(&cx, |counter, _| counter.focus_handle.clone());
    cx.update(|window, cx| {
        focus_handle.dispatch_action(&Increment, window, cx);
    });

    let count = counter.read_with(&cx, |counter, _| counter.count);
    assert_eq!(count, 1);
}
```

### Async Testing

Await the task returned by `cx.spawn`. Updating its weak entity is synchronous and
returns a `Result`; it is not a future. A dropped owner is an expected exit path.

<!-- gpui-check: async-test -->
```rust
use gpui::{AppContext, Context, Task, TestAppContext};

#[derive(Default)]
struct MyComponent {
    loading: bool,
    value: i32,
}

impl MyComponent {
    fn load_data(&self, cx: &mut Context<Self>) -> Task<Option<i32>> {
        cx.spawn(async move |this, cx| {
            this.update(cx, |comp, cx| {
                comp.loading = true;
                cx.notify();
            }).ok()?;
            Some(42)
        })
    }

    fn background_update(&self, cx: &mut Context<Self>) {
        cx.spawn(async move |this, cx| {
            // Background work
            this.update(cx, |comp, cx| {
                comp.value += 10;
                cx.notify();
            }).ok(); // No update if the owner has been dropped.
        }).detach();
    }
}

#[gpui::test]
async fn test_async_operations(cx: &mut TestAppContext) {
    let component = cx.new(|_| MyComponent::default());

    // Test awaited task
    let result = component.update(cx, |comp, cx| comp.load_data(cx)).await;
    assert_eq!(result, Some(42));
    assert!(component.read_with(cx, |comp, _| comp.loading));

    // Test detached task
    component.update(cx, |comp, cx| comp.background_update(cx));

    // Detached tasks don't run until you yield
    let value_before = component.read_with(cx, |comp, _| comp.value);
    assert_eq!(value_before, 0);

    // Run pending tasks
    cx.run_until_parked();

    let value_after = component.read_with(cx, |comp, _| comp.value);
    assert_eq!(value_after, 10);
}
```

### Timer Testing

Start the task so its timer is registered, then advance the test clock explicitly
and drain newly runnable tasks. At the checked revision, `TestAppContext::run_until_parked`
does not advance time; `BackgroundExecutor::run_until_parked` has different
semantics. Do not infer timer behavior from the method name alone.

<!-- gpui-check: timer-test -->
```rust
use gpui::{AppContext, Context, TestAppContext};
use std::time::Duration;

#[derive(Default)]
struct MyComponent {
    action_performed: bool,
}

impl MyComponent {
    fn delayed_action(&self, cx: &mut Context<Self>) {
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(Duration::from_millis(100))
                .await;

            this.update(cx, |comp, cx| {
                comp.action_performed = true;
                cx.notify();
            }).ok();
        }).detach();
    }
}

#[gpui::test]
fn test_timers(cx: &mut TestAppContext) {
    let component = cx.new(|_| MyComponent::default());

    component.update(cx, |comp, cx| comp.delayed_action(cx));

    // Register the timer without advancing time.
    cx.run_until_parked();
    let performed = component.read_with(cx, |comp, _| comp.action_performed);
    assert!(!performed);

    // Verify that the action does not happen early.
    cx.background_executor.advance_clock(Duration::from_millis(99));
    cx.run_until_parked();
    assert!(!component.read_with(cx, |comp, _| comp.action_performed));

    cx.background_executor.advance_clock(Duration::from_millis(1));
    cx.run_until_parked();

    let performed = component.read_with(cx, |comp, _| comp.action_performed);
    assert!(performed);
}
```

### External I/O Testing

For tests involving external systems, use `allow_parking()`:

```rust
#[gpui::test]
async fn test_external_io(cx: &mut TestAppContext) {
    // Allow parking for external I/O
    cx.executor().allow_parking();

    // Simulate external operation
    let (tx, rx) = futures::channel::oneshot::channel();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(10));
        tx.send(42).ok();
    });

    let result = rx.await.unwrap();
    assert_eq!(result, 42);
}
```

## Testing Crash-Free State Management (Re-entrancy)

A re-entrancy panic occurs when a callback reads or updates an entity that is
already borrowed on the current call stack. It can happen during rendering,
updates, or user input. Reads of a different, unborrowed entity are valid.

Exercise the real handler or delegate that previously re-entered the owner, and
assert the resulting state. A `#[should_panic]` test only confirms the failure;
it does not validate the repair. Use `defer_in` when the operation should run
after the current effect cycle has released the owner. It is not a blanket
requirement for nested updates.

### Deferred update example

This test checks both sides of the scheduling boundary: selection stays unchanged
inside the current update and changes after the deferred callback runs.
`defer_in` is flushed with app effects; it does not inherently require an executor
yield. Drain tasks when the actual interaction also schedules async work.

<!-- gpui-check: deferred-test -->
```rust
use gpui::{Context, IntoElement, Render, TestAppContext, Window, div};

#[derive(Default)]
struct Selection {
    selected: Option<usize>,
}

impl Selection {
    fn confirm(&mut self, index: usize, window: &Window, cx: &mut Context<Self>) {
        cx.defer_in(window, move |this, _window, cx| {
            this.selected = Some(index);
            cx.notify();
        });
    }
}

impl Render for Selection {
    fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        div()
    }
}

#[gpui::test]
fn deferred_confirmation_updates_after_borrow_ends(cx: &mut TestAppContext) {
    let window = cx.add_window(|_, _| Selection::default());
    window.update(cx, |view, window, cx| {
        view.confirm(2, window, cx);
        assert_eq!(view.selected, None);
    }).unwrap();

    let selected = window.read_with(cx, |view, _| view.selected).unwrap();
    assert_eq!(selected, Some(2));
}
```

For application-specific list or dropdown delegates, also test confirmation,
cancellation, veto/selection transformation hooks, and rapid repeated changes.
Assert callback order and snapshot contents, not just the absence of a panic.
Create window-dependent controls through a window context; an entity constructor
alone does not supply a `Window`.

## Property Testing

Use random data to test edge cases:

```rust
#[gpui::test(iterations = 10)]
fn test_counter_random_operations(cx: &mut TestAppContext, mut rng: StdRng) {
    let counter = cx.new(|cx| Counter::new(cx));

    let mut expected = 0i32;
    for _ in 0..100 {
        let delta = rng.random_range(-10..=10);
        expected += delta;

        counter.update(cx, |counter, cx| {
            counter.count += delta;
            cx.notify();
        });
    }

    let actual = counter.read_with(cx, |counter, _| counter.count);
    assert_eq!(actual, expected);
}
```

## Distributed Systems Testing

Application-specific sketch: inject a shared fake transport into both components,
then test message delivery between app contexts. GPUI does not supply the
`send_message`/`receive_messages` methods below.

```rust
#[derive(Clone)]
struct NetworkMessage {
    from: String,
    to: String,
    data: i32,
}

#[gpui::test]
fn test_distributed_apps(cx_a: &mut TestAppContext, cx_b: &mut TestAppContext) {
    // Create components in different app contexts
    let comp_a = cx_a.new(|_| MyComponent::new("A".to_string()));
    let comp_b = cx_b.new(|_| MyComponent::new("B".to_string()));

    // Simulate message passing
    comp_a.update(cx_a, |comp, cx| {
        comp.send_message("B", 42, cx);
    });

    // Run async operations
    cx_a.run_until_parked();

    // Verify message received in other context
    comp_b.update(cx_b, |comp, _| {
        comp.receive_messages();
    });

    let messages = comp_b.read_with(cx_b, |comp, _| comp.messages.clone());
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].data, 42);
}
```

### Interleaving Testing

Test concurrent operations with random execution order:

```rust
#[gpui::test(iterations = 10)]
fn test_concurrent_operations(
    cx_a: &mut TestAppContext,
    cx_b: &mut TestAppContext,
    mut rng: StdRng,
) {
    let comp_a = cx_a.new(|_| MyComponent::new());
    let comp_b = cx_b.new(|_| MyComponent::new());

    // Perform random operations across contexts
    for i in 0..20 {
        if rng.random_bool(0.5) {
            comp_a.update(cx_a, |comp, cx| {
                comp.perform_operation(i, cx);
            });
        } else {
            comp_b.update(cx_b, |comp, cx| {
                comp.perform_operation(i, cx);
            });
        }
    }

    // Run all pending operations
    cx_a.run_until_parked();

    // Verify final state
    let state_a = comp_a.read_with(cx_a, |comp, _| comp.state);
    let state_b = comp_b.read_with(cx_b, |comp, _| comp.state);

    // Assert invariants hold despite execution order
    assert!(state_a.is_consistent());
    assert!(state_b.is_consistent());
}
```

## Mocking and Isolation

### Network Mocking

Create mock networks for testing distributed features:

```rust
struct MockNetwork {
    messages: Arc<Mutex<Vec<NetworkMessage>>>,
}

impl MockNetwork {
    fn new() -> Self {
        Self {
            messages: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn send(&self, message: NetworkMessage) {
        self.messages.lock().unwrap().push(message);
    }

    fn receive_all(&self) -> Vec<NetworkMessage> {
        self.messages.lock().unwrap().drain(..).collect()
    }
}

#[gpui::test]
fn test_networked_components(cx: &mut TestAppContext) {
    let network = Arc::new(MockNetwork::new());

    let sender = cx.new(|_| MessageSender::new(network.clone()));
    let receiver = cx.new(|_| MessageReceiver::new(network));

    // Send message
    sender.update(cx, |sender, _| {
        sender.send("Hello");
    });

    // Receive message
    receiver.update(cx, |receiver, _| {
        receiver.receive_all();
    });

    let received = receiver.read_with(cx, |receiver, _| receiver.messages.clone());
    assert_eq!(received, vec!["Hello"]);
}
```
