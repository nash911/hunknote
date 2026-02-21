"""CLI commands for global configuration management."""

import typer

from hunknote import global_config
from hunknote.config import LLMProvider, AVAILABLE_MODELS, API_KEY_ENV_VARS

# Subcommand group for configuration management
config_app = typer.Typer(
    name="config",
    help="Manage global hunknote configuration in ~/.hunknote/",
    add_completion=False,
)


@config_app.command("show")
def config_show() -> None:
    """Show current global configuration."""
    try:
        if not global_config.is_configured():
            typer.echo("No configuration found. Run 'hunknote init' to set up.")
            return

        config = global_config.load_global_config()

        typer.echo("Current hunknote configuration (~/.hunknote/config.yaml):")
        typer.echo()
        typer.echo(f"  Provider: {config.get('provider', 'not set')}")
        typer.echo(f"  Model: {config.get('model', 'not set')}")
        typer.echo(f"  Max Tokens: {config.get('max_tokens', 1500)}")
        typer.echo(f"  Temperature: {config.get('temperature', 0.3)}")

        editor = config.get('editor')
        if editor:
            typer.echo(f"  Editor: {editor}")

        default_ignore = config.get('default_ignore', [])
        if default_ignore:
            typer.echo()
            typer.echo("  Default Ignore Patterns:")
            for pattern in default_ignore:
                typer.echo(f"    - {pattern}")

        typer.echo()

        # Check for API key
        provider_str = config.get('provider')
        if provider_str:
            try:
                provider = LLMProvider(provider_str)
                env_var = API_KEY_ENV_VARS[provider]
                api_key = global_config.get_credential(env_var)

                if api_key:
                    masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
                    typer.echo(f"  API Key ({env_var}): {masked_key}")
                else:
                    typer.echo(f"  API Key ({env_var}): not set")
            except (ValueError, KeyError):
                pass

    except Exception as e:
        typer.echo(f"Error reading configuration: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("set-key")
def config_set_key(
    provider: str = typer.Argument(
        ...,
        help="Provider name (anthropic, openai, google, mistral, cohere, groq, openrouter)"
    )
) -> None:
    """Set or update an API key for a provider."""
    try:
        # Validate provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        env_var = API_KEY_ENV_VARS[llm_provider]

        typer.echo(f"Setting API key for {llm_provider.value}")
        api_key = typer.prompt(f"Enter your {llm_provider.value} API key", hide_input=True)

        global_config.ensure_global_config_dir()
        global_config.save_credential(env_var, api_key)

        typer.echo(f"✓ API key saved for {llm_provider.value}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("set-provider")
def config_set_provider(
    provider: str = typer.Argument(
        ...,
        help="Provider name (anthropic, openai, google, mistral, cohere, groq, openrouter)"
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Model name (optional, will prompt if not provided)"
    )
) -> None:
    """Set the active LLM provider and model."""
    try:
        # Validate provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        # Get model
        if not model:
            models = AVAILABLE_MODELS[llm_provider]
            typer.echo(f"Available models for {llm_provider.value}:")
            for i, m in enumerate(models, 1):
                typer.echo(f"  {i}. {m}")

            model_choice = typer.prompt(f"Select a model (1-{len(models)})", type=int, default=1)
            if model_choice < 1 or model_choice > len(models):
                typer.echo("Invalid choice. Aborting.", err=True)
                raise typer.Exit(1)

            model = models[model_choice - 1]
        else:
            # Validate model
            if model not in AVAILABLE_MODELS[llm_provider]:
                typer.echo(f"Warning: {model} is not in the list of known models for {llm_provider.value}")
                proceed = typer.confirm("Continue anyway?", default=False)
                if not proceed:
                    raise typer.Exit(0)

        global_config.set_provider_and_model(llm_provider, model)

        typer.echo(f"✓ Provider set to: {llm_provider.value}")
        typer.echo(f"✓ Model set to: {model}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("list-providers")
def config_list_providers() -> None:
    """List all available LLM providers."""
    typer.echo("Available LLM providers:")
    typer.echo()
    for provider in LLMProvider:
        typer.echo(f"  • {provider.value}")
    typer.echo()
    typer.echo("Use 'hunknote config list-models <provider>' to see available models.")


@config_app.command("list-models")
def config_list_models(
    provider: str = typer.Argument(
        None,
        help="Provider name (optional, shows all if not provided)"
    )
) -> None:
    """List available models for a provider (or all providers)."""
    if provider:
        # Show models for specific provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        models = AVAILABLE_MODELS[llm_provider]
        typer.echo(f"Available models for {llm_provider.value}:")
        typer.echo()
        for model in models:
            typer.echo(f"  • {model}")
        typer.echo()
    else:
        # Show all providers and their models
        for llm_provider in LLMProvider:
            models = AVAILABLE_MODELS[llm_provider]
            typer.echo(f"{llm_provider.value}:")
            for model in models:
                typer.echo(f"  • {model}")
            typer.echo()

