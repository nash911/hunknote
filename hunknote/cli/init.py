"""CLI command for initializing hunknote configuration."""

import typer

from hunknote import global_config
from hunknote.config import LLMProvider, AVAILABLE_MODELS, API_KEY_ENV_VARS


def init_config() -> None:
    """Initialize hunknote global configuration interactively."""
    typer.echo("Welcome to hunknote! Let's set up your configuration.")
    typer.echo()

    # Check if already configured
    if global_config.is_configured():
        overwrite = typer.confirm(
            "Configuration already exists at ~/.hunknote/config.yaml. Overwrite?",
            default=False
        )
        if not overwrite:
            typer.echo("Keeping existing configuration.")
            raise typer.Exit(0)

    # Select provider
    typer.echo("Available LLM providers:")
    providers = list(LLMProvider)
    for i, provider in enumerate(providers, 1):
        typer.echo(f"  {i}. {provider.value}")

    provider_choice = typer.prompt(
        "Select a provider (1-7)",
        type=int,
        default=3  # Google is index 2 (0-indexed)
    )

    if provider_choice < 1 or provider_choice > len(providers):
        typer.echo("Invalid choice. Aborting.", err=True)
        raise typer.Exit(1)

    selected_provider = providers[provider_choice - 1]

    # Select model
    models = AVAILABLE_MODELS[selected_provider]
    typer.echo()
    typer.echo(f"Available models for {selected_provider.value}:")
    for i, model in enumerate(models, 1):
        typer.echo(f"  {i}. {model}")

    model_choice = typer.prompt(
        f"Select a model (1-{len(models)})",
        type=int,
        default=1
    )

    if model_choice < 1 or model_choice > len(models):
        typer.echo("Invalid choice. Aborting.", err=True)
        raise typer.Exit(1)

    selected_model = models[model_choice - 1]

    # Get API key
    typer.echo()
    env_var = API_KEY_ENV_VARS[selected_provider]
    api_key = typer.prompt(
        f"Enter your {selected_provider.value} API key",
        hide_input=True
    )

    # Save configuration
    try:
        global_config.set_provider_and_model(selected_provider, selected_model)
        global_config.save_credential(env_var, api_key)

        typer.echo()
        typer.echo("✓ Configuration saved to ~/.hunknote/")
        typer.echo(f"  Provider: {selected_provider.value}")
        typer.echo(f"  Model: {selected_model}")
        typer.echo()
        typer.echo("You can now use 'hunknote' in any git repository!")

    except Exception as e:
        typer.echo(f"Error saving configuration: {e}", err=True)
        raise typer.Exit(1)

