
import json
import os

from groq import Groq
from django.conf import settings
from django.db import transaction

from core.models import Dealer, Product
from core.serializers import OrderCreateSerializer


MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

TOOLS = [

    {
        "type": "function",
        "function": {
            "name": "search_parts",
            "description": "Search the parts catalogue by SKU, name, brand, category, or vehicle fitment. Omit optional filters when unknown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": ["string", "null"]},
                    "vehicle": {"type": ["string", "null"]}
                },
                "required": ["query"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check current stock for a product SKU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft_order",
            "description": "Create a DRAFT order for an existing dealer and known product SKUs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dealer_id": {"type": "integer"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string"},
                                "quantity": {"type": "integer"},
                            },
                            "required": ["sku", "quantity"],
                        },
                    },
                },
                "required": ["dealer_id", "items"],
            },
        },
    },
]


def search_parts(query="", category=None, vehicle=None):
    products = Product.objects.all()

    if query:
        from django.db.models import Q
        q_matches = products.filter(
            Q(sku__icontains=query)
            | Q(name__icontains=query)
            | Q(brand__icontains=query)
        )
        if not q_matches.exists():
            alt_query = query.rstrip()
            if alt_query.endswith("s"):
                alt_q_matches = products.filter(
                    Q(sku__icontains=alt_query[:-1])
                    | Q(name__icontains=alt_query[:-1])
                    | Q(brand__icontains=alt_query[:-1])
                )
                if alt_q_matches.exists():
                    q_matches = alt_q_matches
            if not q_matches.exists() and " " in query:
                words = [w.strip() for w in query.split() if w.strip()]
                and_q = Q()
                for w in words:
                    w_term = w[:-1] if w.endswith("s") and len(w) > 3 else w
                    and_q &= (Q(name__icontains=w) | Q(name__icontains=w_term) | Q(sku__icontains=w))
                word_matches = products.filter(and_q)
                if word_matches.exists():
                    q_matches = word_matches

        products = q_matches

    if category:
        products = products.filter(category__iexact=category)

    if vehicle:
        products = products.filter(vehicle_fitment__icontains=vehicle)

    return [
        {
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "vehicle_fitment": p.vehicle_fitment,
            "price": str(p.price),
            "stock": p.stock,
        }
        for p in products[:10]
    ]


def check_stock(sku=""):
    if not sku:
        return {"error": "SKU is required."}

    try:
        product = Product.objects.get(sku__iexact=sku)
    except Product.DoesNotExist:
        return {"error": "Product not found.", "sku": sku}

    return {
        "sku": product.sku,
        "name": product.name,
        "stock": product.stock,
        "price": str(product.price),
    }


def create_draft_order(dealer_id, items):
    serializer = OrderCreateSerializer(
        data={"dealer_id": dealer_id, "items": items}
    )

    if not serializer.is_valid():
        return {
            "error": "Invalid order data.",
            "details": serializer.errors,
        }

    order = serializer.save()

    return {
        "order_number": order.order_number,
        "status": order.status,
        "dealer_id": order.dealer_id,
        "total_amount": str(order.total_amount),
        "items": [
            {
                "sku": item.product.sku,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "line_total": str(item.line_total),
            }
            for item in order.items.select_related("product").all()
        ],
    }


def execute_tool(name, arguments):
    if not isinstance(arguments, dict):
        return {"error": "Invalid arguments."}

    try:
        if name == "search_parts":
            clean_args = {k: v for k, v in arguments.items() if k in ("query", "category", "vehicle")}
            return search_parts(**clean_args)
        if name == "check_stock":
            clean_args = {k: v for k, v in arguments.items() if k in ("sku",)}
            return check_stock(**clean_args)
        if name == "create_draft_order":
            clean_args = {k: v for k, v in arguments.items() if k in ("dealer_id", "items")}
            return create_draft_order(**clean_args)
    except Exception as e:
        return {"error": str(e)}

    return {"error": "Unknown tool."}


def chat_with_assistant(message, session_id, dealer_id=None):
    api_key = getattr(settings, "GROQ_API_KEY", "")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    client = Groq(api_key=api_key)

    # Session memory is isolated by session ID.
    from core.models import AssistantMessage

    history = list(
        AssistantMessage.objects.filter(session_id=session_id)
        .order_by("-created_at")[:12]
    )
    history.reverse()

    system_content = (
        "You are VIKMO DealerDesk, an automotive parts dealer assistant. "
        "Only help with catalogue parts, stock, and draft orders. "
        "For catalogue facts, stock, and orders, use the provided tools. "
        "Never invent prices, stock, dealers, or order numbers. "
        "Create only DRAFT orders. Do not confirm an order until the tool "
        "succeeds. If a request is unrelated to parts, inventory, or orders, "
        "politely decline and explain your scope. Ask for missing dealer or "
        "item details rather than guessing. All catalogue prices, order totals, "
        "and monetary amounts must be displayed in Indian rupees (₹), formatted to "
        "exactly two decimal places. Never use USD or dollar signs."
    )
    if dealer_id:
        system_content += f" The current dealer ID for this session is {dealer_id}."

    messages = [
        {
            "role": "system",
            "content": system_content,
        }
    ]

    messages.extend(
        {"role": row.role, "content": row.content}
        for row in history
        if row.role in ("user", "assistant")
    )
    messages.append({"role": "user", "content": message})

    executed_tools = []
    cited_skus = []
    actions = []

    for _ in range(5):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message.model_dump(exclude_none=True))

        if not assistant_message.tool_calls:
            answer = assistant_message.content or "I couldn't generate a response."
            AssistantMessage.objects.create(
                session_id=session_id, role="user", content=message
            )
            AssistantMessage.objects.create(
                session_id=session_id, role="assistant", content=answer
            )
            return {
                "reply": answer,
                "cited_skus": list(dict.fromkeys(cited_skus)),
                "tool_calls": executed_tools,
                "actions": actions,
            }

        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            raw_args = tool_call.function.arguments
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except Exception:
                    arguments = {}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}

            if tool_name in ("search_parts", "check_stock", "create_draft_order"):
                result = execute_tool(tool_name, arguments)
                executed_tools.append({
                    "name": tool_name,
                    "arguments": arguments,
                })

                if tool_name == "search_parts" and isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and item.get("sku"):
                            cited_skus.append(item["sku"])

                elif tool_name == "check_stock" and isinstance(result, dict) and "error" not in result:
                    sku = result.get("sku")
                    if sku:
                        cited_skus.append(sku)

                elif tool_name == "create_draft_order" and isinstance(result, dict) and "error" not in result and "order_number" in result:
                    actions.append({
                        "type": "draft_order_created",
                        "order_number": result["order_number"],
                    })
                    for item in result.get("items", []):
                        if isinstance(item, dict) and item.get("sku"):
                            cited_skus.append(item["sku"])
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(result),
            })

    raise RuntimeError("The assistant exceeded its tool-call limit.")
