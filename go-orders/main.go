package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	df "github.com/dagflows/sdk-go"
)

// Structs and their json tags are reflected into the manifest as JSON Schema.
type Order struct {
	ID          int64  `json:"id"`
	CustomerID  string `json:"customer_id"`
	AmountCents int64  `json:"amount_cents"`
	Currency    string `json:"currency"`
}

type Orders struct {
	Orders []Order `json:"orders"`
}

type ValidatedOrders struct {
	Orders   []Order `json:"orders"`
	Rejected int     `json:"rejected"`
}

type RiskScore struct {
	OrderID int64   `json:"order_id"`
	Score   float64 `json:"score"`
}

type RiskScores struct {
	Scores []RiskScore `json:"scores"`
}

type Adjustment struct {
	OrderID       int64 `json:"order_id"`
	DiscountCents int64 `json:"discount_cents"`
}

type PricedOrders struct {
	Adjustments []Adjustment `json:"adjustments"`
}

// A node with one parent receives that parent's output, decoded into In.
func validateOrders(ctx *df.Ctx, in Orders) (ValidatedOrders, error) {
	out := ValidatedOrders{Orders: make([]Order, 0, len(in.Orders))}
	for _, order := range in.Orders {
		if !strings.EqualFold(order.Currency, "usd") || order.AmountCents <= 0 {
			out.Rejected++
			continue
		}

		order.Currency = "usd"
		out.Orders = append(out.Orders, order)
	}

	// ctx.Log() is a *slog.Logger attached to the workflow run's log stream.
	ctx.Log().Info("validated orders", "kept", len(out.Orders), "rejected", out.Rejected)

	return out, nil
}

// applyPricing discounts every order with a risk score below 0.34 by DISCOUNT_CENTS.
func applyPricing(ctx *df.Ctx, in RiskScores) (PricedOrders, error) {
	// A variable is read inside the node, since the build that emits the manifest has none.
	discountCents, err := strconv.ParseInt(os.Getenv("DISCOUNT_CENTS"), 10, 64)
	if err != nil || discountCents < 0 {
		return PricedOrders{}, fmt.Errorf("DISCOUNT_CENTS is %q, want a whole number of cents", os.Getenv("DISCOUNT_CENTS"))
	}

	out := PricedOrders{Adjustments: make([]Adjustment, 0, len(in.Scores))}
	discounted := 0
	for _, scored := range in.Scores {
		var discount int64
		if scored.Score < 0.34 {
			discount = discountCents
			discounted++
		}

		out.Adjustments = append(out.Adjustments, Adjustment{OrderID: scored.OrderID, DiscountCents: discount})
	}

	ctx.Log().Info("priced orders", "scored", len(in.Scores), "discounted", discounted, "discount_cents", discountCents)

	return out, nil
}

func main() {
	// A project contributing nodes to a workflow another project owns uses an unnamed workflow.
	wf := df.NewWorkflow("", df.WorkflowOptions{})

	// wf.External names a node of another project by its key, typed with what this node
	// expects of it, which Dagflows checks against what that project declares at build time.
	wf.Node(validateOrders, wf.External[Orders]("ingest_orders"), df.NodeOptions{Key: "validate_orders"})
	// Env names the variables a node gets. Their values are set on Dagflows.
	wf.Node(applyPricing, wf.External[RiskScores]("score_risk"), df.NodeOptions{Key: "apply_pricing", Env: []string{"DISCOUNT_CENTS"}})

	// Dispatches SDK commands: dumps the workflow graph during build,
	// and invokes the target node handler during execution.
	df.Main()
}
