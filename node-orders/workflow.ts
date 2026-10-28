import { Workflow } from "@dagflows/sdk/authoring";
import type { Ctx, Int } from "@dagflows/sdk/runtime";

// Interfaces are reflected into the manifest as JSON Schema, read from this source
// by the typescript package when the manifest is built. An Int is reflected as an
// int64 integer, which the Python and Go integers on the other side of each edge need.
// A number is a JSON number, which never satisfies an integer.
interface Order {
  id: Int;
  customer_id: string;
  amount_cents: Int;
  currency: string;
}

interface Orders {
  orders: Order[];
}

interface ValidatedOrders {
  orders: Order[];
  rejected: Int;
}

interface EnrichedOrder extends Order {
  tier: string;
}

interface EnrichedOrders {
  orders: EnrichedOrder[];
  rejected: Int;
}

interface RiskScores {
  scores: { order_id: Int; score: number }[];
}

// A project contributing nodes to a workflow another project owns uses an unnamed workflow.
export const wf = new Workflow();

// externalNode names a node of another project by its key, typed with what this
// project expects of it, which Dagflows checks against what that project declares.
const validateOrders = wf.externalNode<ValidatedOrders>("validate_orders");
const ingestOrders = wf.externalNode<Orders>("ingest_orders");

// Node handlers must be exported so Dagflows can discover them. Annotating input
// puts it in the manifest as the node's input schema.
export const enrichCustomers = wf.node(
  function enrichCustomers ({ ctx, input }: { ctx: Ctx; input: ValidatedOrders }): EnrichedOrders {
    // A variable is read inside the node, since the build that emits the manifest has none.
    const goldTier = process.env.GOLD_TIER_CENTS ?? "";
    if (!/^\d+$/.test(goldTier)) {
      throw new Error(`GOLD_TIER_CENTS is "${goldTier}", want a whole number of cents`);
    }

    const goldTierCents = Number(goldTier);
    const orders = input.orders.map((order) => ({
      ...order,
      tier: order.amount_cents >= goldTierCents ? "gold" : "standard",
    }));

    ctx.log.info(`enriched ${orders.length} orders, gold from ${goldTierCents} cents`);

    return { orders, rejected: input.rejected };
  },
  // env names the variables a node gets. Their values are set on Dagflows.
  { key: "enrich_customers", depends: [validateOrders], env: ["GOLD_TIER_CENTS"] },
);

export const scoreRisk = wf.node(
  function scoreRisk ({ ctx, input }: { ctx: Ctx; input: Orders }): RiskScores {
    const scores = input.orders.map((order) => ({
      order_id: order.id,
      score: (order.id % 10) / 10,
    }));

    ctx.log.info(`scored ${scores.length} orders`);

    return { scores };
  },
  { key: "score_risk", depends: [ingestOrders] },
);
