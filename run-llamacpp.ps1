<#
.SYNOPSIS
    Serve a local GGUF model through llama.cpp with Vulkan and speculative decoding.

.DESCRIPTION
    Ollama is the easy way to run a model and not the fast way on this hardware. On a Strix
    Halo part the GPU and CPU share one memory pool, and llama.cpp's Vulkan backend with
    multi-token prediction reads the weights once while evaluating several tokens, which is
    what lifts a dense 27B model off its memory-bandwidth ceiling.

    The practical difference is not only speed. Asked to find government announcements among
    five headlines, gemma4:12b found one; qwen3.8 through this server found all three, with
    its reasoning separated into `reasoning_content` instead of consuming the whole output
    budget. Some jobs in this platform simply need the larger model.

    Weights are read straight out of Ollama's blob store, so there is no second copy of a
    16 GB file on disk.

    ONE MODEL AT A TIME. This machine shares 32 GB between CPU and GPU, and qwen3.8 at 32k
    context with MTP draft buffers leaves no room for a second model. Running a task routed to
    Ollama while this server is up produced "vk::Device::allocateMemory: ErrorOutOfDeviceMemory"
    -- gemma4:12b was holding 8.1 GB and the allocation failed. `ollama stop <model>` frees it.
    Either route every task here, or keep Ollama unloaded while this runs.

.EXAMPLE
    .\run-llamacpp.ps1
    .\run-llamacpp.ps1 -Model gemma4:12b -Port 8081
    .\run-llamacpp.ps1 -DraftMax 2      # lower, if acceptance is poor
#>
[CmdletBinding()]
param(
    # Ollama model name. Its GGUF blob is resolved from the local manifest.
    [string]$Model = "qwen3.8:latest",
    [int]$Port = 8080,
    [int]$ContextSize = 32768,

    # Tokens drafted per cycle by multi-token prediction. Four suits sequential extraction --
    # reading transcripts, parsing financials. If acceptance drops below roughly 60% the
    # verification overhead stops paying for itself; try 2 or 3.
    [int]$DraftMax = 4,

    [string]$LlamaCppDir = "C:\AI Projects\llama.cpp-bin"
)

$ErrorActionPreference = "Stop"

$server = Join-Path $LlamaCppDir "llama-server.exe"
if (-not (Test-Path $server)) {
    throw @"
No llama-server at $server.

Download the prebuilt Vulkan build rather than compiling -- this machine has no C toolchain,
and building one costs far more than the 35 MB binary:
  https://github.com/ggml-org/llama.cpp/releases  ->  llama-*-bin-win-vulkan-x64.zip
Extract it to $LlamaCppDir.
"@
}

# Resolve the model's GGUF out of Ollama's blob store instead of copying it.
$modelsRoot = Join-Path $env:USERPROFILE ".ollama\models"
$name, $tag = $Model.Split(":")
if (-not $tag) { $tag = "latest" }
$manifest = Join-Path $modelsRoot "manifests\registry.ollama.ai\library\$name\$tag"
if (-not (Test-Path $manifest)) {
    throw "No Ollama manifest for '$Model' at $manifest. Pull it first: ollama pull $Model"
}

$layers = (Get-Content $manifest -Raw | ConvertFrom-Json).layers
$modelLayer = $layers | Where-Object { $_.mediaType -like "*.model" } | Select-Object -First 1
if (-not $modelLayer) { throw "No model layer in the manifest for '$Model'." }

$blob = Join-Path $modelsRoot ("blobs\" + $modelLayer.digest.Replace(":", "-"))
if (-not (Test-Path $blob)) { throw "Model blob missing: $blob" }

$sizeGb = [math]::Round((Get-Item $blob).Length / 1GB, 1)
Write-Host "Serving $Model ($sizeGb GB) on http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "  Vulkan, MTP draft depth $DraftMax, ${ContextSize}-token context" -ForegroundColor DarkGray

# -ctk q8_0: an 8-bit K cache. Not a tuning preference -- multi-token prediction allocates
#   extra transient buffers during lookahead, and at 32k context on 32 GB of shared memory the
#   full-precision cache is what pushes it over.
# --reasoning-format deepseek: keeps thinking in `reasoning_content` and the answer in
#   `content`. Without it a thinking model spends its whole output budget reasoning and returns
#   an empty string -- which reads exactly like a document with nothing to say.
& $server `
    -m $blob `
    --alias $name `
    --gpu-layers 99 `
    --flash-attn on `
    -c $ContextSize `
    -ctk q8_0 `
    --spec-type draft-mtp `
    --spec-draft-n-max $DraftMax `
    --jinja `
    --reasoning-format deepseek `
    --host 127.0.0.1 `
    --port $Port
