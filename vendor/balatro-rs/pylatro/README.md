# pylatro

Use [pyo3](https://pyo3.rs) to add python bindings to the rust balatro engine.

### Overview

I wanted to try and experiment with applying reinforcement learning to balatro. For someone without
any experience in that area, the easiest implementation I found was [gymnasium](https://gymnasium.farama.org/index.html).
I used [pyo3](https://pyo3.rs) to provide python bindings to the rust library and then setup the roughest gymnasium
training environment and agent (I really do not know what I am doing here). So far it compiles and runs
but nothing really works correctly.

