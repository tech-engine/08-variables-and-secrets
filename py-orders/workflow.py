import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass

from dagflows.authoring import Workflow
from dagflows.runtime import Ctx, Inputs

# A named workflow owns the workflow's settings. Exactly one project in the workspace names it.
wf = Workflow("order-pipeline")


# Dataclasses are reflected into the manifest as JSON Schema.
@dataclass
class Order:
    id: int
    customer_id: str
    amount_cents: int
    currency: str


@dataclass
class Orders:
    orders: list[Order]


@dataclass
class EnrichedOrder(Order):
    tier: str


@dataclass
class EnrichedOrders:
    orders: list[EnrichedOrder]
    rejected: int


@dataclass
class Adjustment:
    order_id: int
    discount_cents: int


@dataclass
class PricedOrders:
    adjustments: list[Adjustment]


@dataclass
class Report:
    total_orders: int
    rejected: int
    gross_cents: int
    discount_cents: int
    net_cents: int
    by_tier: dict[str, int]


@dataclass
class SignedReport:
    report: Report
    # The HMAC-SHA256 of the report's JSON, its keys sorted and no spaces, keyed by REPORT_SIGNING_KEY.
    signature: str


# A trigger is a typed event source. A manual run, or a webhook bound to the trigger,
# delivers the event, and Dagflows checks it against Orders before the run starts.
orders_received = wf.trigger("orders_received", event=Orders)


# A node depending on a trigger receives the event as its input. Node keys default to
# the decorated function name unless overridden in @wf.node().
# The return annotation becomes the node's output schema.
@wf.node(depends=[orders_received])
def ingest_orders(batch: Orders, ctx: Ctx) -> Orders:
    # ctx.trigger describes the delivery that started the run, None when no trigger did.
    if ctx.trigger:
        ctx.log.info("%s event %s received at %s", ctx.trigger.kind, ctx.trigger.id, ctx.trigger.received_at)

    # ctx provides structured logging attached to this workflow run.
    ctx.log.info("run %s: ingested %d orders", ctx.run.workflow_run_id, len(batch.orders))

    return batch


# external_node names a node of another project by its key. Its type is what this
# project expects of that node, checked against what that project declares at build time.
enriched = wf.external_node("enrich_customers", EnrichedOrders)
priced = wf.external_node("apply_pricing", PricedOrders)


# A node with several parents takes inputs. Each parent's output is reached by its
# handle and decoded into the handle's type. env names the variables a node gets. Their
# values are set on Dagflows, and a secret's value is masked wherever the node prints it.
@wf.node(depends=[enriched, priced], env=["REPORT_SIGNING_KEY"])
def build_report(inputs: Inputs, ctx: Ctx) -> SignedReport:
    orders = inputs[enriched].value()
    adjustments = inputs[priced].value()

    discounts = {adjustment.order_id: adjustment.discount_cents for adjustment in adjustments.adjustments}

    gross = sum(order.amount_cents for order in orders.orders)
    discount = sum(discounts.get(order.id, 0) for order in orders.orders)

    by_tier: dict[str, int] = {}
    for order in orders.orders:
        by_tier[order.tier] = by_tier.get(order.tier, 0) + 1

    report = Report(
        total_orders=len(orders.orders),
        rejected=orders.rejected,
        gross_cents=gross,
        discount_cents=discount,
        net_cents=gross - discount,
        by_tier=by_tier,
    )

    ctx.log.info(
        "report: %d orders, %d rejected, %d cents net of %d discount",
        report.total_orders,
        report.rejected,
        report.net_cents,
        report.discount_cents,
    )

    # A variable is read inside the node, since the build that emits the manifest has none.
    key = os.environ.get("REPORT_SIGNING_KEY", "")
    if not key:
        raise ValueError("REPORT_SIGNING_KEY is not set")

    body = json.dumps(asdict(report), sort_keys=True, separators=(",", ":"))
    signature = hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()

    ctx.log.info("signed the report: %s", signature)

    return SignedReport(report=report, signature=signature)
