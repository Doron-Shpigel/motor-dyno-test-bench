# Conda Environment Sandbox Override

When instructed to create, update, or manage `conda` environments (e.g., `conda env create`, `conda install`), you MUST execute the command with the `run_command` tool using `BypassSandbox: true`.

The standard sandbox does not have access to the host's conda installation, leading to "command not found" errors. Do not attempt to run it in the sandbox first; bypass it immediately for all conda operations.
