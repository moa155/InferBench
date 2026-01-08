# MeluXina Setup Guide for UBenchAI Framework

This guide helps you set up the UBenchAI Framework on the MeluXina supercomputer.

## Prerequisites

1. **MeluXina Account**: You need an active account on MeluXina
2. **SSH Access**: Ability to SSH to `login.lxp.lu`
3. **Project Allocation**: You should have a project allocation for compute time

## Step 1: Connect to MeluXina

**Important:** MeluXina uses port **8822** for SSH connections.

```bash
# Connect to MeluXina login node (note the port!)
ssh u103032@login.lxp.lu -p 8822 -i ~/.ssh/id_ed25519_mlux

# Or with your username:
ssh YOUR_USERNAME@login.lxp.lu -p 8822 -i ~/.ssh/id_ed25519_mlux
```

### Recommended: Add SSH Config

Add this to your `~/.ssh/config` for easier access:

```
Host meluxina
    HostName login.lxp.lu
    User u103032
    Port 8822
    IdentityFile ~/.ssh/id_ed25519_mlux
```

Then connect with just: `ssh meluxina`

## Step 2: Set Up Your Environment

### Load Required Modules

```bash
# Load Python (MeluXina uses module system)
module load Python/3.11.3-GCCcore-12.3.0

# Load Apptainer (for containers)
module load Apptainer/1.2.4-GCCcore-12.3.0

# Optionally, add these to your ~/.bashrc for persistence:
echo 'module load Python/3.11.3-GCCcore-12.3.0' >> ~/.bashrc
echo 'module load Apptainer/1.2.4-GCCcore-12.3.0' >> ~/.bashrc
```

### Install Poetry

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to PATH
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# Verify installation
poetry --version
```

## Step 3: Clone and Set Up the Project

```bash
# Navigate to your project directory
cd /project/home/YOUR_PROJECT/

# Clone the repository
git clone https://github.com/YOUR_USERNAME/UBenchAI-Framework.git
cd UBenchAI-Framework

# Install dependencies
poetry install

# Verify installation
poetry run ubenchai --version
poetry run ubenchai --help
```

## Step 4: Configure the Framework

### Create Environment File

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your settings
nano .env
```

Update the following in your `.env`:

```bash
# Your MeluXina username
MELUXINA_USER=your_username

# Your project allocation code (e.g., p200301)
MELUXINA_PROJECT=your_project

# Your preferred partition
MELUXINA_PARTITION=gpu
```

## Step 5: Set Up Container Images

Container images should be stored in your project space:

```bash
# Create directory for container images
mkdir -p /project/home/YOUR_PROJECT/containers

# Update .env with the path
SIF_IMAGES_DIR=/project/home/YOUR_PROJECT/containers
```

### Building/Pulling Container Images

#### vLLM Container

```bash
# Pull vLLM container (on a compute node with internet access)
# You may need to do this via a Slurm job

cd /project/home/YOUR_PROJECT/containers

# Option 1: Pull from Docker Hub
apptainer pull docker://vllm/vllm-openai:latest

# Option 2: Build from definition file
apptainer build vllm-latest.sif docker://vllm/vllm-openai:latest
```

#### Ollama Container

```bash
apptainer pull docker://ollama/ollama:latest
```

#### Qdrant Container

```bash
apptainer pull docker://qdrant/qdrant:latest
```

## Step 6: Verify SLURM Access

```bash
# Check your available partitions
sinfo

# Check your account/project
sacctmgr show associations user=$USER

# View your current jobs
squeue --me

# Check available resources
scontrol show partition gpu
```

## Step 7: Test Basic Functionality

### Test CLI

```bash
# Activate Poetry environment (Poetry 2.0+)
eval $(poetry env activate)

# Or use poetry run for individual commands
poetry run ubenchai info
poetry run ubenchai --help
```

### Test SLURM Job Submission

Create a simple test job:

```bash
cat > test_job.sh << 'EOF'
#!/bin/bash
#SBATCH --job-name=ubenchai-test
#SBATCH --time=00:05:00
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --output=test_%j.out
#SBATCH --error=test_%j.err

# Load modules
module load Python/3.11.3-GCCcore-12.3.0
module load Apptainer/1.2.4-GCCcore-12.3.0

# Print environment info
echo "Running on node: $(hostname)"
echo "Python version: $(python3 --version)"
echo "Apptainer version: $(apptainer --version)"
nvidia-smi

echo "Test completed successfully!"
EOF

# Submit the job
sbatch test_job.sh

# Check job status
squeue --me
```

## Directory Structure on MeluXina

Recommended setup:

```
/project/home/YOUR_PROJECT/
├── UBenchAI-Framework/     # Main project
├── containers/             # Apptainer images
│   ├── vllm-latest.sif
│   ├── ollama-latest.sif
│   └── qdrant-latest.sif
├── models/                 # AI models
│   └── llama-2-7b/
├── data/                   # Benchmark datasets
└── results/                # Benchmark outputs
```

## Common Issues and Solutions

### Issue: Module not found

```bash
# Make sure modules are loaded
module load Python/3.11.3-GCCcore-12.3.0
module list
```

### Issue: Permission denied for containers

```bash
# Check file permissions
ls -la /project/home/YOUR_PROJECT/containers/

# Fix permissions if needed
chmod +x *.sif
```

### Issue: Out of quota

```bash
# Check your disk usage
lfs quota -u $USER /project/home/YOUR_PROJECT/

# Clean up if needed
rm -rf ~/.cache/pip
rm -rf ~/.cache/apptainer
```

### Issue: Job pending too long

```bash
# Check why job is pending
squeue --me --long

# Try a different partition or reduce resources
# Edit your job script or recipe accordingly
```

## SSH Port Forwarding for Monitoring

When running monitoring services, you'll need to forward ports:

```bash
# From your local machine, forward Prometheus and Grafana ports
# Note: MeluXina uses port 8822!
ssh -p 8822 -L 9090:COMPUTE_NODE:9090 -L 3000:COMPUTE_NODE:3000 u103032@login.lxp.lu -i ~/.ssh/id_ed25519_mlux

# Or if you have SSH config set up:
ssh -L 9090:COMPUTE_NODE:9090 -L 3000:COMPUTE_NODE:3000 meluxina
```

Replace `COMPUTE_NODE` with the actual node name where your services are running (e.g., `mel2091`).

## Next Steps

1. ✅ Environment set up
2. ✅ Framework installed
3. ⏳ Container images ready
4. ⏳ Run first benchmark

Continue to the main README for usage instructions!
