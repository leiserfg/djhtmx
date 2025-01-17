from uuid import uuid4

from django import template
from django.conf import settings
from django.core.signing import Signer
from django.template.base import Node, Parser, Token
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .. import json
from ..component import Component

register = template.Library()

CSRF_HEADER_NAME = settings.CSRF_HEADER_NAME[5:].replace('_', '-')


@register.inclusion_tag(
    'htmx/headers.html',
    takes_context=True,
    name='htmx-headers',
)
def htmx_headers(context):
    """Loads all the necessary scripts to make this work

    Use this tag inside your `<header></header>`.
    """
    return {
        'csrf_header_name': CSRF_HEADER_NAME,
        'csrf_token': context.get('csrf_token'),
        'DEBUG': settings.DEBUG,
    }


@register.simple_tag(takes_context=True)
def htmx(context, _name, id=None, **state):
    """Inserts an HTMX Component.

    Pass the component name and the initial state:

        ```html
        {% htmx 'AmazinData' data=some_data %}
        ```
    """
    id = id or f'hx-{uuid4().hex}'
    component = Component._build(_name, context['request'], id, state)
    return mark_safe(component._render())


@register.simple_tag(takes_context=True, name='hx-tag')
def hx_tag(context):
    """Adds initialziation data to your root component tag.

    When your component starts, put it there:

        ```html
        {% load htmx %}
        <div {% hx-tag %}>
          ...
        </div>
        ```
    """
    html = [
        'id="{id}"',
        'hx-post="{url}"',
        'hx-trigger="render"',
        'hx-headers="{headers}"',
    ]

    if context.get('hx_swap_oob'):
        html.append('hx-swap-oob="true"')
    else:
        html.append('hx-swap="outerHTML"')

    component = context['this']
    return format_html(
        ' '.join(html),
        id=context['id'],
        url=event_url(component, 'render'),
        headers=json.dumps(
            {
                'X-Component-State': Signer().sign(component._state_json),
            }
        ),
    )


@register.simple_tag(takes_context=True)
def on(context, _trigger, _event_handler=None, **kwargs):
    """Binds an event to a handler

    If no trigger is provided, it assumes the default one by omission, in this
    case `click`, for an input is `change`:

        ```html
        <button {% on 'inc' %}>+</button>
        ```

    You can pass it explicitly:

        ```html
        <button {% on 'click' 'inc' %}>+</button>
        ```

    You can also pass explicit arguments:

        ```html
        <button {% on 'inc' amount=2 %}>+2</button>
        ```

    Remember that together with the explicit arguments, all fields with a
    `name` are passed as implicit arguments to your event handler.

    If you wanna do more advanced stuff read:
    [hx-trigger](https://htmx.org/attributes/hx-trigger/)

    """
    if not _event_handler:
        _event_handler = _trigger
        _trigger = None

    component = context['this']

    assert callable(
        getattr(component, _event_handler, None)
    ), f'{component._name}.{_event_handler} event handler not found'

    html = ' '.join(
        filter(
            None,
            [
                'hx-post="{url}" ' 'hx-target="#{id}" ',
                'hx-include="#{id} [name]" ',
                'hx-trigger="{trigger}" ' if _trigger else None,
                'hx-vals="{vals}" ' if kwargs else None,
            ],
        )
    )

    return format_html(
        html,
        trigger=_trigger,
        url=event_url(component, _event_handler),
        id=context['id'],
        vals=json.dumps(kwargs) if kwargs else None,
    )


def event_url(component, event_handler):
    return reverse(
        'djhtmx.endpoint',
        kwargs={
            'component_name': component._name,
            'event_handler': event_handler,
        },
    )


# Shortcuts and helpers


@register.tag()
def cond(parser: Parser, token: Token):
    """Prints some text conditionally

        ```html
        {% cond {'works': True, 'does not work': 1 == 2} %}
        ```
    Will output 'works'.
    """
    dict_expression = token.contents[len('cond ') :]
    return CondNode(dict_expression)


@register.tag(name='class')
def class_cond(parser: Parser, token: Token):
    """Prints classes conditionally

    ```html
    <div {% class {'btn': True, 'loading': loading, 'falsy': 0} %}></div>
    ```

    If `loading` is `True` will print:

    ```html
    <div class="btn loading"></div>
    ```
    """
    dict_expression = token.contents[len('class ') :]
    return ClassNode(dict_expression)


class CondNode(Node):
    def __init__(self, dict_expression):
        self.dict_expression = dict_expression

    def render(self, context):
        terms = eval(self.dict_expression, context.flatten())
        return ' '.join(term for term, ok in terms.items() if ok)


class ClassNode(CondNode):
    def render(self, *args, **kwargs):
        text = super().render(*args, **kwargs)
        return f'class="{text}"'
