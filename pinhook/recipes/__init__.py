"""Recipes: custom commands written as data files, not Python.

Plugins add filters for recipe templates with recipes.template_filter.
"""
from .templates import Template, TemplateError, template_filter

__all__ = ['Template', 'TemplateError', 'template_filter']
