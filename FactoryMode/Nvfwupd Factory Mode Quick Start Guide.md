# Nvfwupd Factory Mode - Quick Start Guide

This guide walks you through setting up and running the nvfwupd tool in Factory mode after cloning the repository.

## Workflow Overview

The nvfwupd tool in Factory mode follows a structured workflow to ensure reliable firmware updates across factory devices. The tool automatically collects debug information using nvdebug when failures occur, providing detailed diagnostic data for troubleshooting.

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Config File   │    │    Flow File     │    │  Log Directory  │
│  (Credentials   │    │   (Operations    │    │   (Required)    │
│   & Settings)   │    │   & Sequences)   │    │                 │
└─────────┬───────┘    └─────────┬────────┘    └─────────┬───────┘
          │                      │                       │
          └──────────────┬───────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Factory Flow       │
              │  Orchestrator       │
              │  (nvfwupd.py)       │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Load & Validate   │
              │   Configuration     │
              │   + Flow Steps      │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Execute Flow      │
              │   Steps             │
              └──────────┬──────────┘
                         │
         ┌───────────────┼
         │               │               
         ▼               ▼               
┌─────────────┐  ┌─────────────┐
│   Compute   │  │   Switch    │
│   Tray      │  │   Tray      │
│             │  │             │
│ ┌─────────┐ │  │ ┌─────────┐ │
│ │   BMC   │ │  │ │   BMC   │ │
│ │ Update  │ │  │ │ Update  │ │
│ └─────────┘ │  │ └─────────┘ │
│ ┌─────────┐ │  │ ┌─────────┐ │
│ │   HMC   │ │  │ │  NVOS   │ │
│ │ Update  │ │  │ │ Update  │ │
│ └─────────┘ │  │ └─────────┘ │
│ ┌─────────┐ │  │ ┌─────────┐ │
│ │   NIC   │ │  │ │  BIOS   │ │
│ │ Update  │ │  │ │ Update  │ │
│ └─────────┘ │  │ └─────────┘ │
└─────┬───────┘  └─────┬───────┘
      │                │
      └────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │  Progress Tracking  │
              │  & Status Updates   │
              │                     │
              │ • Real-time logs    │
              │ • JSON progress     │
              │ • nvdebug on errors │
              │ • Recovery flows    │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Final Status      │
              │   & Log Output      │
              │                     │
              │ • Success/Failure   │
              │ • Detailed logs     │
              │ • Performance data  │
              │ • Error reports     │
              └─────────────────────┘
```

### Key Workflow Features

- **Unified Orchestration**: Single tool manages all device types (compute, switch)
- **Sequential Operations**: Reliable step-by-step execution with comprehensive error handling
- **Progress Tracking**: Real-time status updates and comprehensive logging
- **Error Recovery**: Automatic retry mechanisms and optional recovery flows
- **Validation**: Firmware version verification ensures successful updates

## Table of Contents
1. [Tool Extraction](#1-tool-extraction)
2. [Choose Configuration Template](#2-choose-configuration-template)
3. [Choose Flow File](#3-choose-flow-file)
4. [Pre-Configure System Settings](#4-pre-configure-system-settings)
5. [Runtime Credential Configuration](#5-runtime-credential-configuration)
6. [Launch the Tool](#6-launch-the-tool)
7. [Check Flow Status](#7-check-flow-status)
8. [Log Folder Structure](#log-folder-structure)

---

## 1. Tool Extraction

Clone the open-source NVIDIA nvfwupd repository from GitHub.

### Clone the Repository
```bash
# Clone the nvfwupd repository
git clone https://github.com/NVIDIA/open-nvfwupd.git

# Navigate to the nvfwupd directory
cd open-nvfwupd/
```

Expected directory structure:
```
nvfwupd/
├── nvfwupd.py                           # Main launcher script
├── FactoryMode/
│   ├── FactoryFlowYAMLFiles/           # Configuration and flow templates
│   ├── Utilities/                      # Helper scripts
│   │   ├── config_patcher.py          # Configuration patcher utility
│   │   └── flow_status_checker.py     # Status checker utility
│   └── factory_flow_orchestrator.py   # Core orchestrator
└── requirements.txt                    # Python dependencies
```

### Install Dependencies
```bash
# Install required Python packages
pip install -r requirements.txt
```

---

## 2. Choose Configuration Template

Select the appropriate configuration template for your system architecture.

### Available Configuration Templates

| Template | File Location | System Type | Description |
|----------|---------------|-------------|-------------|
| GB300 | `FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_factory_flow_config.yaml` | GB300 Systems | Configuration for GB300 compute nodes and switches |

The GB300 configuration template (`GB300_factory_flow_config.yaml`) provides the base settings for GB300 compute nodes and switches with full HMC/BMC support, DOT security configuration, and both local and remote switch update options.

**Note**: All configuration variables and their detailed usage are covered in [Step 4: Pre-Configure System Settings](#4-pre-configure-system-settings).

---

## 3. Choose Flow File  

Select the appropriate flow file based on the operation you want to perform.

### Available GB300 Flow Files

#### Main Production Flows

These are the primary flows used for complete factory updates:

**GB300 Complete Compute Update**
- **`GB300_compute_flow.yaml`** - Complete compute tray firmware update (BMC, HMC, SBIOS, DOT security)
  - **Prerequisite:** The `_nosbios` HMC firmware package must be repacked to include customer SBIOS.

- **`GB300_compute_NIC_flow.yaml`** - Network interface updates (BlueField-3, ConnectX-8)
  - **Prerequisite:** This is an inband update that requires the system to boot to the OS.

**GB300 Switch Update**  
- **`GB300_nvswitch_flow.yaml`** - Switch firmware updates (Switch BMC, BIOS, NVOS, CPLD)
  - **Prerequisite:** This is an inband update that requires the system to boot to the OS.

#### Flow Variants

The following flows are specialized variants of the main flows for specific scenarios:

**Compute Flow Variants:**
  
- **`GB300_seperate_sbios_compute_flow.yaml`** - Separate SBIOS variant
  - **Purpose**: Updates SBIOS firmware separately from HMC, but in the same AC Cycle.
  - **Modified Variables**: Uses `cpu_sbios_bundle_name` in addition to HMC nosbios bundle.

---

## 4. Pre-Configure System Settings

Use the `FactoryMode/Utilities/config_patcher.py` utility to create a customized runtime configuration based on the GB300 template (`GB300_factory_flow_config.yaml`). This step configures all non-credential settings that are shared across nodes in your factory environment.

### Configuration File Sections

The GB300 template contains several key sections:

#### System Settings
- **Connection Details**: IP addresses, usernames, passwords for BMC, OS, and switch access  
- **Timeout Values**: SSH, Redfish, and retry configurations
- **Bundle Paths**: Firmware bundle locations and filenames
- **Version Validation**: Expected firmware versions for verification
- **Security Settings**: DOT (Device of Trust) configuration for secure boot

#### Configuration Examples
```yaml
# Switch Tray Configuration
switch:
  bmc:
    ip: ""                    # Switch BMC IP address
    username: ""              # Switch BMC username  
    password: ""              # Switch BMC password

# Compute Tray Configuration  
compute:
  bmc:
    ip: ""                    # Compute BMC IP address
    username: ""              # Compute BMC username
    password: ""              # Compute BMC password
  os:
    ip: ""                    # Compute OS IP address
    username: ""              # Compute OS username
    password: ""              # Compute OS password

```

### Main Production Flow Requirements

#### Common Variables (Required for All Flows)

| Variable | Description | Example Value |
|----------|-------------|---------------|
| `nvdebug_path` | Path to nvdebug tool for error log collection | `/local/path/to/nvdebug/tool/binary` |
| `output_mode` | Display mode for orchestrator output | `all`, `gui`, `compute1`, `none` |

#### Main Flow Files and Their Required Variables

**1. GB300_compute_flow.yaml - Complete Compute Update**

| Variable | Purpose | Example Value |
|----------|---------|---------------|
| `compute_bundles_folder` | Path to all compute firmware bundles | `/path/to/folder/containing/all/fwpkg-bundles` |
| `no_sbios_hmc_firmware_bundle_name` | HMC bundle containing customer SBIOS | `Compute Tray/Compute Tray Firmware/HMC/250719.1.1/nvfw_GB300-P4059-0301_0041_250719.1.1_custom_prod-signed.fwpkg` |
| `bmc_firmware_bundle_name` | BMC firmware bundle (if updating BMC) | `Compute Tray/Compute Tray Firmware/BMC/250719.1.0/nvfw_GB300-P4058-0301_0042_250719.1.0_custom_prod-signed.fwpkg` |
| `pem_encoded_key` | Customer DOT public key | `-----BEGIN PUBLIC KEY-----...` |
| `ap_firmware_signature` | Customer DOT firmware signature | `customer_signature_string` |
| `compute.DOT` | DOT security mode | `NoDOT`, `Volatile`, or `Locking` |
| Version variables | Expected firmware versions for validation | `bmc_final_version=GB200Nvl-25.07-7`, `hmc_final_version=GB200Nvl-25.07-7` |

**2. GB300_compute_NIC_flow.yaml - NIC Firmware Update**

| Variable | Purpose | Example Value |
|----------|---------|---------------|
| `compute_bundles_folder` | Path to compute firmware bundles | `/path/to/folder/containing/all/fwpkg-bundles` |
| `bluefield_3_inband_image_name` | BlueField-3 NIC firmware image | `Compute Tray/Compute Tray Firmware/BF3_NIC/32.45.1600/fw-BlueField-3-rel-32_45_1600-900-9D3B6-00CN-P_Ax-NVME-20.4.1-UEFI-21.4.13-UEFI-22.4.14-UEFI-14.38.16-FlexBoot-3.7.500.signed.bin` |
| `connect_x8_inband_image_name` | ConnectX-8 NIC firmware image | `Compute Tray/Compute Tray Firmware/CX/40.45.3048/fw-ConnectX8-rel-40_45_3048-900-9X86E-00CX-SP0_Ax-UEFI-14.38.16-FlexBoot-3.7.500.signed.bin` |
| `mft_bundle_name` | Mellanox Firmware Tools package | `Tools/MFT/4.32.0-6017/mft-4.32.0-6017-linux-arm64-deb` |

**3. GB300_nvswitch_flow.yaml - Switch Firmware Update**

| Variable | Purpose | Example Value |
|----------|---------|---------------|
| `nvswitch_bundles_folder` | Path to switch firmware bundles | `/path/to/folder/containing/all/fwpkg-bundles` |
| `switch_bmc_bundle_name` | Switch BMC firmware bundle | `Switch Tray/Switch Tray Firmware/BMC/250719.1.0/nvfw_GB300-Switch_BMC_250719.1.0.fwpkg` |
| `switch_cpld_file_name` | Switch CPLD file (extracted .bin) | `Switch Tray/Switch Tray Firmware/CPLD/250719.1.0/switch_cpld_250719.1.0.bin` |
| `switch_bios_bundle_name` | Switch BIOS firmware bundle | `Switch Tray/Switch Tray Firmware/BIOS/250719.1.0/GB300_Switch_BIOS_250719.1.0.fwpkg` |
| `switch_nvos_bundle_name` | Switch NVOS operating system bundle | `Switch Tray/Switch Tray Firmware/NVOS/5.7.0/cumulus-linux-5.7.0-cl5.8.0.bin` |
| Switch version variables | Expected switch firmware versions | `switch_bmc_final_version`, `switch_nvos_final_version`, etc. |

### Auxiliary Flow Files

These specialized flows modify or add to the main flow requirements:

| Auxiliary Flow | Based On | Modified/Additional Variables | Purpose |
|----------------|----------|------------------------------|---------|
| `GB300_seperate_sbios_compute_flow.yaml` | Compute main | **Adds**: `cpu_sbios_bundle_name` | Separate SBIOS in same AC cycle |

### Using config_patcher.py

The config_patcher.py script allows you to modify YAML configuration files using command-line arguments or patch files.

#### Basic Syntax
```bash
# Using command line patching
python FactoryMode/Utilities/config_patcher.py <output_file> --set <key=value> [--source <baseline_config>]

# Using YAML patch file
python FactoryMode/Utilities/config_patcher.py --patch-file <patch_file.yaml> <output_file> [--source <baseline_config>]
```

### Configuration Examples

#### Basic Compute Flow Configuration
```bash
# Create GB300 compute configuration from template
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --source FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_factory_flow_config.yaml \
  --set "variables.nvdebug_path=/local/path/to/nvdebug/tool/binary" \
  --set "variables.output_mode=all" \
  --set "variables.compute_bundles_folder=/path/to/folder/containing/all/fwpkg-bundles" \
  --set "variables.no_sbios_hmc_firmware_bundle_name=Compute Tray/Compute Tray Firmware/HMC/250719.1.1/nvfw_GB300-P4059-0301_0041_250719.1.1_custom_prod-signed.fwpkg" \
  --set "compute.DOT=NoDOT"
```

#### Basic Switch Flow Configuration
```bash
# Create GB300 switch configuration from template
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --source FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_factory_flow_config.yaml \
  --set "variables.nvdebug_path=/local/path/to/nvdebug/tool/binary" \
  --set "variables.output_mode=all" \
  --set "variables.nvswitch_bundles_folder=/path/to/folder/containing/all/fwpkg-bundles" \
  --set "variables.switch_bmc_bundle_name=Switch Tray/Switch Tray Firmware/BMC/250719.1.0/nvfw_GB300-Switch_BMC_250719.1.0.fwpkg" \
  --set "variables.switch_cpld_file_name=Switch Tray/Switch Tray Firmware/CPLD/250719.1.0/switch_cpld_250719.1.0.bin"
```

### Alternative Method: Using YAML Patch Files

For production deployments, you can use YAML patch files to standardize firmware versions and bundle names across your factory environment. This method is particularly useful when NVIDIA provides official firmware release patches.

#### Creating a Patch File

Create a patch file containing the firmware bundle names and versions (but not credentials or local paths):

**Example: `gb300_release_25.07.7_patch.yaml`**
```yaml
variables:
  # Display and debug settings
  output_mode: all
  
  # Compute firmware bundles with official release paths  
  bmc_firmware_bundle_name: "Compute Tray/Compute Tray Firmware/BMC/250719.1.0/nvfw_GB300-P4058-0301_0042_250719.1.0_custom_prod-signed.fwpkg"
  no_sbios_hmc_firmware_bundle_name: "Compute Tray/Compute Tray Firmware/HMC/250719.1.1/nvfw_GB300-P4059-0301_0041_250719.1.1_custom_prod-signed.fwpkg"
  
  # NIC firmware images
  bluefield_3_inband_image_name: "Compute Tray/Compute Tray Firmware/BF3_NIC/32.45.1600/fw-BlueField-3-rel-32_45_1600-900-9D3B6-00CN-P_Ax-NVME-20.4.1-UEFI-21.4.13-UEFI-22.4.14-UEFI-14.38.16-FlexBoot-3.7.500.signed.bin"
  connect_x8_inband_image_name: "Compute Tray/Compute Tray Firmware/CX/40.45.3048/fw-ConnectX8-rel-40_45_3048-900-9X86E-00CX-SP0_Ax-UEFI-14.38.16-FlexBoot-3.7.500.signed.bin"
  
  # Tools
  mft_bundle_name: "Tools/MFT/4.32.0-6017/mft-4.32.0-6017-linux-arm64-deb"
  nvdebug_path: "/local/path/to/nvdebug/tool/binary"
  
  # Expected firmware versions for validation (GB300-25.07-7 release)
  bmc_final_version: "GB300-25.07-7"
  bmc_erot_final_version: "01.04.0031.0000_n04"  
  bmc_backplane_cpld_final_version: "0B_04_02"
  
  hmc_final_version: "GB300-25.07-7"
  hmc_cpld_final_version: "0.22"
  hmc_fpga_final_version: "1.44" 
  hmc_erot_final_version: "01.04.0031.0000_n04"
  hmc_cpu_erot_final_version: "01.04.0031.0000_n04"
  hmc_fpga_erot_final_version: "01.04.0031.0000_n04"
  
  cpu_final_version: "02.04.12"
  hmc_gpu_final_version: "97.10.3E.00.05"

# Standard settings for factory environment
settings:
  default_retry_count: 2
  default_wait_after_seconds: 1
  ssh_timeout: 30
  redfish_timeout: 30
  execute_on_error: "default_error_handler"

# DOT configuration
compute:
  DOT: "NoDOT"  # Set to Volatile or Locking as needed
```

#### Using the Patch File

Apply the patch to your base configuration template:

```bash
# Apply firmware release patch to GB300 template
python FactoryMode/Utilities/config_patcher.py \
  --patch-file gb300_release_25.07.7_patch.yaml \
  GB300_runtime_config.yaml \
  --source FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_factory_flow_config.yaml
```

Then add your site-specific settings (paths and credentials):

```bash
# Add site-specific paths and credentials
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --set "variables.compute_bundles_folder=/path/to/folder/containing/all/fwpkg-bundles" \
  --set "connection.compute.bmc.ip=YOUR_COMPUTE_BMC_IP" \
  --set "connection.compute.bmc.username=YOUR_BMC_USERNAME" \
  --set "connection.compute.bmc.password=YOUR_BMC_PASSWORD" \
  --set "connection.compute.os.ip=YOUR_COMPUTE_OS_IP" \
  --set "connection.compute.os.username=YOUR_OS_USERNAME" \
  --set "connection.compute.os.password=YOUR_OS_PASSWORD"
```

#### Benefits of Patch Files

1. **Version Control**: Standardized firmware versions across factory locations
2. **NVIDIA Updates**: Easy distribution of new firmware releases  
3. **Separation of Concerns**: Firmware details separate from site-specific credentials
4. **Audit Trail**: Clear tracking of what firmware versions are deployed
5. **Automation Friendly**: Easy integration with CI/CD pipelines

### Best Practices

1. **Bundle Organization**: Keep all firmware bundles in organized directories by system type
2. **Version Consistency**: Use consistent version naming across all components  
3. **Path Verification**: Always verify file paths exist before running flows
4. **Template Reuse**: Create one base configuration per system type, copy for each deployment
5. **Documentation**: Document your customer-specific DOT keys and signatures securely

---

## 5. Runtime Credential Configuration

**Important**: Credentials must be configured for EVERY node separately, while system settings (Step 4) only need to be done once.

### Configure Node Credentials

Update connection credentials for each device in your environment:

#### Configure Compute Node Credentials
```bash
# Set compute BMC credentials
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --set "connection.compute.bmc.ip=YOUR_COMPUTE_BMC_IP" \
  --set "connection.compute.bmc.username=YOUR_BMC_USERNAME" \
  --set "connection.compute.bmc.password=YOUR_BMC_PASSWORD"

# Set compute OS credentials  
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --set "connection.compute.os.ip=YOUR_COMPUTE_OS_IP" \
  --set "connection.compute.os.username=YOUR_OS_USERNAME" \
  --set "connection.compute.os.password=YOUR_OS_PASSWORD"
```

#### Configure Switch Credentials
```bash
# Set switch BMC credentials
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --set "connection.switch.bmc.ip=YOUR_SWITCH_BMC_IP" \
  --set "connection.switch.bmc.username=YOUR_SWITCH_BMC_USERNAME" \
  --set "connection.switch.bmc.password=YOUR_SWITCH_BMC_PASSWORD"

# Set switch OS credentials
python FactoryMode/Utilities/config_patcher.py GB300_runtime_config.yaml \
  --set "connection.switch.os.ip=YOUR_SWITCH_OS_IP" \
  --set "connection.switch.os.username=YOUR_SWITCH_OS_USERNAME" \
  --set "connection.switch.os.password=YOUR_SWITCH_OS_PASSWORD"
```


### Credential Management Best Practices

1. **Security**: Store credentials securely and avoid hardcoding in scripts
2. **Per-Node Configuration**: Each node requires its own credential configuration  
3. **Validation**: Test credentials before running firmware updates
4. **Backup**: Keep backup configurations for recovery scenarios

---

## 6. Launch the Tool

Execute the factory flow using the nvfwupd tool in Factory mode with your configuration and flow files.

### Basic Launch Command

```bash
python nvfwupd.py factory_mode \
  -c GB300_runtime_config.yaml \
  -f FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_compute_flow.yaml \
  -l /logs/firmware_update
```

### Launch Examples for Production Flows

#### Full Compute Update (Two-Step Process)

**Step 1: Main Compute Firmware Update**
```bash
python nvfwupd.py factory_mode \
  -c GB300_runtime_config.yaml \
  -f FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_compute_flow.yaml \
  -l /logs/gb300_compute_main_update
```

**Step 2: NIC Firmware Update**  
```bash
python nvfwupd.py factory_mode \
  -c GB300_runtime_config.yaml \
  -f FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_compute_NIC_flow.yaml \
  -l /logs/gb300_compute_nic_update
```

#### Full Switch Update
```bash  
python nvfwupd.py factory_mode \
  -c GB300_runtime_config.yaml \
  -f FactoryMode/FactoryFlowYAMLFiles/GB300Flow/GB300_nvswitch_flow.yaml \
  -l /logs/gb300_switch_update
```

### Command Parameters

| Parameter | Short | Description | Required | Example |
|-----------|-------|-------------|----------|---------|
| `--config_path` | `-c` | Path to configuration YAML file | Yes | `GB300_runtime_config.yaml` |
| `--flow_path` | `-f` | Path to flow YAML file | Yes | `GB300_compute_flow.yaml` |
| `--log_dir` | `-l` | Log directory path | Yes | `/logs/firmware_update` |

### Output Modes

The tool supports different output modes configured in your runtime config:

- **`gui`**: Rich interactive interface with live progress bars
- **`all`**: Complete console output with static progress table
- **`<device_id>`**: Filtered output for specific device (e.g., `compute1`)  
- **`other`**: General messages only

---

## 7. Check Flow Status

Use the `flow_status_checker.py` utility to monitor and analyze flow execution progress.

### Using flow_status_checker.py

The flow status checker analyzes log files and JSON progress data to provide detailed status information.

#### Basic Status Check
```bash
python FactoryMode/Utilities/flow_status_checker.py /path/to/log/directory
```

#### Verbose Status Check
```bash
python FactoryMode/Utilities/flow_status_checker.py --verbose /path/to/log/directory
```

### Status Check Examples

#### Check Status of Recent Factory Flow
```bash
# Check status using log directory from launch
python FactoryMode/Utilities/flow_status_checker.py /logs/gb300_compute_update

# Expected output:
# ============================================================
# Flow Status Check Results
# ============================================================
# 
# Flow: GB300 Compute Flow
# Status: Completed Successfully
# Completed Steps: 25/25
# Total Runtime: 2847.5 seconds (47.5 minutes)
# Steps with Errors: 0
# Optional Flows Executed: 1
# 
# ============================================================
```

#### Verbose Status with Error Details
```bash
python FactoryMode/Utilities/flow_status_checker.py --verbose /logs/failed_update

# Provides detailed information including:
# - Step-by-step execution status
# - Error messages and stack traces  
# - Retry attempts and outcomes
# - Optional flow triggers and results
# - Performance metrics per step
```

### Status Information Details

The flow status checker provides:

1. **Overall Flow Status**: Success, failure, or in-progress
2. **Step Completion**: Number of completed vs total steps
3. **Timing Information**: Total runtime and step durations
4. **Error Analysis**: Detailed error messages and affected steps
5. **Recovery Actions**: Optional flows that were triggered
6. **Performance Metrics**: Step timing and retry statistics

### Status Return Codes

| Return Code | Status | Description |
|-------------|--------|-------------|
| 0 | Success | Flow completed successfully |
| 1 | Failure | Flow failed or encountered errors |
| 2 | In Progress | Flow is currently running |
| 3 | Unknown | Unable to determine flow status |

### Monitoring Running Flows

For long-running flows, you can periodically check status:

```bash
# Monitor flow progress every 5 minutes
while true; do
  echo "$(date): Checking flow status..."
  python FactoryMode/Utilities/flow_status_checker.py /logs/current_update
  sleep 300
done
```

---

## Troubleshooting

### Common Issues and Solutions

#### Configuration Issues
- **Missing Variables**: Use `config_patcher.py` to verify all required variables are set
- **Invalid Paths**: Ensure firmware bundle paths exist and are accessible
- **Connection Errors**: Verify IP addresses and credentials are correct

#### Flow Execution Issues  
- **Permission Errors**: Ensure the tool has appropriate access to firmware files
- **Network Timeouts**: Check network connectivity to target devices
- **Firmware Compatibility**: Verify firmware versions match your hardware

#### Status Checking Issues
- **Missing Log Files**: Ensure log directory path is correct
- **Incomplete Status**: Wait for flow completion before final status check
- **Permission Errors**: Ensure read access to log directory

### Getting Help

1. **Verbose Logging**: Use verbose mode for detailed execution information
2. **Status Checking**: Use `flow_status_checker.py` to analyze failed flows  
3. **Log Analysis**: Review log files in the specified log directory
4. **Configuration Validation**: Verify configuration files with YAML validators

---

## Log Folder Structure

The factory flow tool generates comprehensive logging information to track execution progress and aid in troubleshooting. Understanding the log folder structure helps with monitoring and analysis.

### Log Directory Organization

When you specify a log directory with the `-l` flag, the following structure is created:

```
/your/log/directory/
├── factory_flow_orchestrator.log          # Main orchestrator log
├── compute_factory_flow.log               # Compute device operations log
├── switch_factory_flow.log                # Switch device operations log (if used)
├── flow_progress.json                     # Real-time progress tracking JSON
├── nvfwupd_config.yaml                   # Configuration snapshot
└── boot_*.log                             # Boot/system initialization logs
```

### Log File Contents

#### Main Orchestrator Logs

**`factory_flow_orchestrator.log`**
- Flow initialization and configuration loading
- Step-by-step execution progress
- Jump and retry logic decisions
- Optional flow triggers and results
- High-level error handling and recovery
- Final flow completion status

**Example entries:**
```
2025-01-15 10:30:15 INFO: Loading flow from GB300_compute_flow.yaml
2025-01-15 10:30:16 INFO: Executing step: check_bmc_version
2025-01-15 10:30:18 INFO: Step completed successfully, jumping to: skip_bmc_updates
2025-01-15 10:30:20 WARNING: Step failed, executing optional flow: bmc_recovery_flow
```

#### Device-Specific Logs

**`compute_factory_flow.log` / `switch_factory_flow.log`**
- Device connection establishment
- Firmware bundle validation
- Update operation detailed progress
- Version checking and validation
- Device-specific error handling

**Example entries:**
```
2025-01-15 10:30:16 INFO: Connecting to compute BMC at YOUR_COMPUTE_BMC_IP
2025-01-15 10:30:17 INFO: Validating firmware bundle: nvfw_GB300-P4058-0301_0042_250719.1.0_custom_prod-signed.fwpkg
2025-01-15 10:30:20 INFO: Starting PLDM firmware update for BMC
2025-01-15 10:32:45 INFO: Firmware update completed successfully
```

#### Progress Tracking Files

**`flow_progress.json`**
Real-time JSON tracking of flow execution:
```json
{
  "timestamp": "2025-01-15T10:30:15.123456",
  "flows": {
    "GB300 Compute Flow": {
      "status": "In Progress",
      "current_step": "flash_hmc_firmware_including_sbios",
      "completed_steps": 12,
      "total_steps": 25,
      "total_runtime": 847.5,
      "steps_executed": [
        {
          "step_name": "check_bmc_version",
          "duration": 2.333,
          "status": "completed",
          "final_result": true
        }
      ]
    }
  }
}
```

**`flow_execution_summary.json`**
Complete execution summary generated at completion:
```json
{
  "overall_status": "Success",
  "total_execution_time": 1847.5,
  "total_steps": 25,
  "failed_steps": 0,
  "retry_count": 3,
  "optional_flows_executed": 1,
  "devices_updated": ["compute1"],
  "firmware_versions_validated": {
    "bmc_final_version": "GB300-25.07-7",
    "hmc_final_version": "GB300-25.07-7"
  }
}
```

#### Additional Log Details

**Note**: For specific details about additional device-specific logs, error output formats, and debugging information generated by the tool, please refer to the actual tool documentation or run the tool to observe the complete logging structure. This guide avoids making assumptions about implementation details not explicitly documented.

### Log Analysis Tips

#### Monitoring Active Flows
```bash
# Watch real-time progress
tail -f /logs/factory_flow_orchestrator.log

# Check current status
python FactoryMode/Utilities/flow_status_checker.py /logs/
```

#### Troubleshooting Failed Updates
```bash
# Find error patterns in main log files
grep -i "error\|fail\|timeout" /logs/*.log

# Check specific device log details
grep -A5 -B5 "error" /logs/compute_factory_flow.log
grep -A5 -B5 "error" /logs/switch_factory_flow.log
```

#### Performance Analysis
```bash
# Extract step timing information
jq '.flows[].steps_executed[] | {name: .step_name, duration: .duration}' /logs/flow_progress.json

# Find slowest operations
jq '.flows[].steps_executed | sort_by(.duration) | reverse | .[0:5]' /logs/flow_progress.json
```

### Log Retention and Management

#### Best Practices
1. **Archive Logs**: Keep logs for each firmware update session for audit trails
2. **Disk Space**: Monitor log directory size - firmware updates can generate substantial logs
3. **Cleanup**: Remove old log files after analysis is complete
4. **Backup**: Include critical logs (flow_progress.json, summary.json) in backup procedures

#### Automated Log Management
```bash
# Archive completed flow logs
tar -czf "flow_logs_$(date +%Y%m%d_%H%M%S).tar.gz" /logs/
mv flow_logs_*.tar.gz /archive/factory_logs/

# Cleanup old log files older than 7 days
find /logs/ -name "*.log" -mtime +7 -delete
```

---

## Next Steps

After completing this quick start guide:

1. **Test Configuration**: Run a simple flow to validate your setup
2. **Automate Deployment**: Create scripts for repeated operations
3. **Monitor Performance**: Track timing and success rates
4. **Scale Operations**: Extend configuration for multiple nodes
5. **Integration**: Integrate with your existing factory automation

For detailed technical information, refer to the comprehensive documentation in `FactoryMode/README.md`.
