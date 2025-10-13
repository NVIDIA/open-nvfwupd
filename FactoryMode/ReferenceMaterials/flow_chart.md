> SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
>
> SPDX-License-Identifier: Apache-2.0

# Nvfwupd Flow Framework - Architecture Flowchart

This document provides a comprehensive flowchart showing how the `factory_flow_orchestrator.py` currently works.

## Architecture Flowchart

```mermaid
flowchart TD
    A[Start: FactoryFlowOrchestrator] --> B["Initialize<br/>(config_path)"]
    B --> C[Load variables & output mode]
    C --> D[Setup logging & progress tracker]

    D --> E[load_flow_from_yaml]
    E --> F[Parse & Validate YAML]
    F --> G[Expand Variables]
    G --> H[Load Optional Flows]
    H --> I[Convert to Flow Objects]

    I --> J[execute_flow]
    J --> K{Step Type?}

    K -->|IndependentFlow| L[Group consecutive flows]
    K -->|FlowStep or ParallelFlowStep| M[Wrap in IndependentFlow]

    L --> N{Multiple flows?}
    N -->|Yes| O[Execute in Parallel]
    N -->|No| P[Execute Sequential]
    M --> P

    O --> Q[All flows complete]
    P --> Q

    Q --> R{Success?}
    R -->|Yes| S{More steps?}
    R -->|No| T[Handle Failure]

    T --> U{Optional Flow?}
    U -->|Yes| V[Execute Optional Flow]
    U -->|No| W{Jump on Failure?}

    V --> X{Recovered?}
    X -->|Yes| Y[Retry Step]
    X -->|No| Z[Flow Failed]

    W -->|Yes| AA[Jump to Target]
    W -->|No| AB{Error Handler?}

    AB -->|Yes| AC[Execute Handler]
    AB -->|No| Z

    AC --> AD{Continue?}
    AD -->|Yes| S
    AD -->|No| Z

    Y --> R
    AA --> J

    S -->|Yes| J
    S -->|No| AE[Flow Complete]

    Z --> AF[Execute Flow Error Handler]
    AF --> AE

    AE --> AG[Close Connections]
    AG --> AH[End]

    classDef configClass fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef flowClass fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef deviceClass fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    classDef errorClass fill:#ffebee,stroke:#b71c1c,stroke-width:2px
    classDef successClass fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px

    class B,C,D configClass
    class E,F,G,H,I,J,K,L,M,N,O,P,Q,S flowClass
    class R,Y deviceClass
    class T,U,V,W,X,Z,AA,AB,AC,AD,AF errorClass
    class AE,AG,AH successClass
```

## Flow Execution Overview

### 1. **Initialization**
- Load configuration from `factory_flow_config.yaml`
- Set output mode (GUI, log, JSON, or none)
- Initialize progress tracking and logging

### 2. **Load Flow from YAML**
- Parse and validate flow definition YAML file
- Expand variables (`${variable_name}`)
- Load optional flows (recovery procedures)
- Convert YAML to flow objects

### 3. **Execute Flow**
- Process each step in the flow definition
- Wrap individual steps into execution containers
- Execute multiple flows in parallel when possible
- Track progress and timing

### 4. **Step Execution**
- Execute operations on target devices (compute, switch, power shelf)
- Retry on failure with configurable retry count
- Execute steps sequentially or in parallel as defined

### 5. **Failure Recovery**
- **Optional Flow**: Execute recovery procedure and retry
- **Jump on Failure**: Branch to different step sequence
- **Error Handler**: Custom error handling logic
- **Abort**: Terminate flow if no recovery available

### 6. **Completion**
- Execute flow-level error handler if flow failed
- Close all device connections
- Finalize progress tracking and logging

## Key Components

### **Input Configuration Files**
1. **factory_flow_config.yaml**: Main configuration
   - Device connection details (IP, credentials)
   - Variables for reuse across flows
   - Output mode settings
   - Default retry counts and timeouts

2. **Flow YAML Files**: Define execution sequences
   - Steps to execute on each device
   - Optional flows for recovery
   - Jump targets for branching logic
   - Error handlers

### **Flow Step Types**
- **FlowStep**: Single operation on a device
- **ParallelFlowStep**: Multiple operations running concurrently
- **IndependentFlow**: Self-contained flow that can run independently

### **Device Types**
- **Compute**: Server/node operations via BMC
- **Switch**: Network switch operations
- **Power Shelf**: Power supply unit management

### **Recovery Mechanisms**
1. **Retry**: Automatically retry failed operations (configurable count)
2. **Optional Flow**: Execute recovery procedure, then retry original step
3. **Jump on Failure**: Branch to alternate step sequence
4. **Error Handler**: Custom logic to handle or log failures

### **Execution Modes**
- **Sequential**: Steps execute one after another
- **Parallel**: Multiple flows or steps execute simultaneously
- Determined by how steps are structured in YAML 