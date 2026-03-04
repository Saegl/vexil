# Vexil Language Design Document

(Draft v0.2)

## 1. Overview

Vexil is a compiled, general-purpose programming language designed for:

- Python-like readability
- Native performance
- Modern safety features
- Minimal conceptual complexity

### Core philosophy

- Prefer simple semantics over clever abstractions.
- Avoid hidden control flow.
- Favor explicit error handling.
- Maintain a small core language with strong tooling.

## 2. Syntax

### 2.1 Blocks

Blocks are defined with braces.

```vexil
if x > 10 {
    print("big")
}
```

Indentation has no semantic meaning.

### 2.2 Statement termination

Semicolons are optional.

These are equivalent:

```vexil
let x = 10
let y = 20
let x = 10;
let y = 20;
```

### 2.3 Comments

```vexil
# line comment
```

## 3. Variables and Constants

### 3.1 Variables

Variables use `let`.

```vexil
let x = 10
x = x + 1
```

Variables are mutable by default.

### 3.2 Constants

Constants use `const`.

```vexil
const PI = 3.14159
```

Rules:

- Evaluated at compile time
- Immutable
- Usable in type expressions and optimizations

## 4. Booleans and Logical Operators

The `bool` type has two values: `true` and `false`.

Logical operators use keywords:

```vexil
if x > 0 and x < 10 {
    print("in range")
}

if not done or force {
    run()
}
```

- `and` — short-circuit logical AND
- `or` — short-circuit logical OR
- `not` — logical negation

## 5. Functions

Functions are defined using `def`.

```vexil
def add(a: int, b: int) -> int {
    return a + b
}
```

Functions can exist outside classes.

### 4.1 Default arguments

```vexil
def connect(host: string, port: int = 5432) -> Conn
```

### 4.2 Named arguments

```vexil
connect(host="localhost", port=5432)
```

### 4.3 No function overloading

To keep the language simple:

- Functions cannot be overloaded by type
- Names must be unique

## 6. Classes

Classes are GC-managed reference types.

```vexil
class User {
    name: string
    age: int
}
```

### 5.1 Constructors

Construction uses the class name.

```vexil
let u = User("Alice", 25)
```

Constructor defined via `init`.

```vexil
class User {
    name: string
    age: int

    def init(name: string, age: int) {
        self.name = name
        self.age = age
    }
}
```

### 5.2 Methods

Methods are regular functions with `self`.

```vexil
class Counter {
    value: int

    def inc(self) {
        self.value = self.value + 1
    }
}
```

### 5.3 Inheritance

```vexil
class Animal {
    def speak(self) {}
}

class Dog(Animal) {
    def speak(self) {
        print("woof")
    }
}
```

## 7. Enums

Enums are tagged unions.

```vexil
enum Shape {
    Circle(radius: float)
    Rect(w: float, h: float)
    Point
}
```

## 8. While Loops

```vexil
while x < 10 {
    x = x + 1
}
```

The `while` loop repeats a block while the condition is true.

## 8.1 For Loops

The `for` loop iterates over a range of values using the builtin `range` function.

```vexil
for i in range(10) {
    print(i)
}
```

`range` supports 1 to 3 arguments:

```vexil
for i in range(10) { ... }           # 0..9
for i in range(1, 10) { ... }        # 1..9
for i in range(0, 10, 2) { ... }     # 0, 2, 4, 6, 8
```

`range` is a compiler builtin (pure LLVM codegen, no runtime needed).

## 9. Pattern Matching

Pattern matching uses `match`.

```vexil
def area(s: Shape) -> float {
    return match s {
        Circle(r) => 3.14 * r * r
        Rect(w, h) => w * h
        Point => 0
    }
}
```

Guarantees:

- Exhaustive checking
- Destructuring
- Wildcard `_`

## 10. Error Handling

Vexil does not use exceptions. Errors are values.

### 8.1 Result type

```vexil
enum Result<T, E> {
    Ok(T)
    Err(E)
}
```

Example:

```vexil
def parse_int(text: string) -> Result<int, ParseError>
```

### 8.2 Error propagation

Operator `?`.

```vexil
def load(path: string) -> Result<string, IOError> {
    let text = read_file(path)?
    return Ok(text)
}
```

### 8.3 Panic

Unrecoverable errors:

```vexil
panic("unexpected state")
```

Used for programmer mistakes.

## 11. Generics

Generics are supported in functions and classes.

### 9.1 Generic functions

```vexil
def identity<T>(x: T) -> T {
    return x
}
```

### 9.2 Generic classes

```vexil
class Box<T> {
    value: T
}
```

### 9.3 Constraints

Constraints use base classes.

```vexil
def max<T: Comparable>(a: T, b: T) -> T
```

Meaning: `T` must extend `Comparable`.

No trait system is included.

## 12. Core Types

Primitive types: `int`, `float`, `bool`, `string`, `bytes`

### 10.1 Collections

Standard library provides:

```vexil
List<T>
Map<K, V>
Set<T>
```

### 10.2 Option

Nullability uses `Option`.

```vexil
enum Option<T> {
    Some(T)
    None
}
```

## 13. Modules

Every file is a module. There is no `module` keyword.

### 11.1 Imports

Filesystem syntax:

```vexil
import "math.vx"
import "nodes/simple.vx"
import "./utils.vx"
```

Selective import:

```vexil
from "math.vx" import add
```

### 11.2 Exports

Symbols must be exported.

```vexil
export def add(a: int, b: int) -> int {
    return a + b
}
```

Non-exported symbols are private.

## 14. Memory Model

Vexil uses garbage collection.

Characteristics:

- Automatic memory management
- No ownership system
- No explicit pointer types
- Objects allocated on heap

## 15. Standard Library

Initial standard library modules:

- `std.io`
- `std.fs`
- `std.net`
- `std.time`
- `std.json`
- `std.math`
- `std.collections`
- `std.regex`
- `std.process`
- `std.test`

## 16. Tooling

Compiler commands:

```bash
vexil build
vexil run
vexil test
vexil fmt
vexil lsp
```

## 17. Example Program

```vexil
from "math.vx" import add

def main() {
    let x = add(3, 4)
    print(x)
}
```

## 18. Language Summary

Vexil combines:

- Python-like readability
- Compiled performance
- Explicit error handling
- Enums + pattern matching
- GC memory model
- Modern tooling
