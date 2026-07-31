"""ToolCall-TR — doğrulanabilir Türkçe tool-calling veri üretim pipeline'ı.

Katmanlama `.importlinter` tarafından zorlanır::

    models/, turkish/  ->  hiçbir iç bağımlılık
    registry/          ->  models
    providers/         ->  models, registry, turkish
    execution/         ->  models, registry, providers
    groundtruth/       ->  models, execution
    validation/        ->  models          (execution DEĞİL)
    cli/               ->  her şey; cli'yi kimse import etmez
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
