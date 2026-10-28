# Step 8: Variables and Secrets

The workflow from step 7, with the values that change without a deploy, and a key that must stay out of the repository, kept on Dagflows instead of in the code. `apply_pricing` reads its discount and `enrich_customers` its gold tier from plain variables, and `build_report` signs the report with a secret key.

```
               orders_received (trigger)
                          |
                  ingest_orders (Python)
                   /                  \
    validate_orders (Go)        score_risk (TypeScript)
            |                            |
   enrich_customers (TypeScript)   apply_pricing (Go)
     GOLD_TIER_CENTS                DISCOUNT_CENTS
                   \                  /
                   build_report (Python)
                    REPORT_SIGNING_KEY
```

### What you'll learn
- How to name the variables a node gets, in each language.
- How to set them on a workflow and on a project.
- How a secret differs from a plain variable.
- How a new value reaches the next run without a deploy.

## What's New

Compared with [step 7](https://github.com/dagflows/examples/tree/main/07-webhook):

- `apply_pricing` takes its discount from `DISCOUNT_CENTS`, and `enrich_customers` the amount from which an order is gold from `GOLD_TIER_CENTS`. Both are plain variables, values an operator changes without a deploy.
- `build_report` signs the report with `REPORT_SIGNING_KEY`, a secret. Its output is the report and its signature, which whoever receives the report checks with the same key.
- The code names the variables a node gets, and Dagflows holds their values, on the organization, a project or the workflow.

## Files

```
dagflows.yaml          workspace: the workflow name, its projects and the TypeScript entry module
orders.json            the five orders, a run's payload
py-orders/
  workflow.py          the workflow, the orders_received trigger, ingest_orders and build_report, which signs
  requirements.txt     pinned Dagflows SDK dependency
go-orders/
  main.go              validate_orders and apply_pricing, which reads DISCOUNT_CENTS
  go.mod               module declaration requiring the Dagflows SDK
node-orders/
  workflow.ts          enrich_customers, which reads GOLD_TIER_CENTS, and score_risk
  package.json         project manifest depending on @dagflows/sdk, with typescript and @types/node for development
  package-lock.json    pinned dependency tree (required for npm ci)
```

## Code

[py-orders/workflow.py](py-orders/workflow.py), [go-orders/main.go](go-orders/main.go) and [node-orders/workflow.ts](node-orders/workflow.ts) each name one variable on one node. A node gets the variables it names, as environment variables, and no others:

| | Python | Go | TypeScript |
|---|---|---|---|
| One node's | `@wf.node(env=["NAME"])` | `df.NodeOptions{Env: []string{"NAME"}}` | `wf.node(fn, { env: ["NAME"] })` |
| Every node's | `Workflow("name", env=["NAME"])` | `df.WorkflowOptions{Env: []string{"NAME"}}` | `new Workflow("name", { env: ["NAME"] })` |
| Reading one | `os.environ["NAME"]` | `os.Getenv("NAME")` | `process.env.NAME` |

- Only the project that names the workflow can name variables for every node, so here each node names its own.
- A variable is read inside the node. The build that emits the manifest runs the code with none.
- A name is letters, digits and `_`, not starting with a digit. Names starting with `DAGFLOWS_` or `LD_`, and `PATH`, `HOME`, `TMPDIR`, `USER`, `LOGNAME`, `PWD`, `SHELL` and `PYTHONUNBUFFERED`, are the platform's.

## Run Locally

Locally nothing sets the variables, so export the values Dagflows would give the nodes, then run [step 6's commands](https://github.com/dagflows/examples/tree/main/06-trigger#run-locally) from this directory in the same shell:

```bash
export DISCOUNT_CENTS=500 GOLD_TIER_CENTS=10000 REPORT_SIGNING_KEY=$(openssl rand -hex 32)
```

A node started without its variable fails and names it, for example `DISCOUNT_CENTS is "", want a whole number of cents`. The last command now prints the report and its signature. Check the signature with the key:

```bash
jq -jcS .output.data.report /tmp/out.json | openssl dgst -sha256 -hmac "$REPORT_SIGNING_KEY" | awk '{print $NF}'
jq -r .output.data.signature /tmp/out.json
```

The two lines are the same. `-jcS` writes the report as `build_report` signed it, its keys sorted, without spaces or a final newline.

## Run on Dagflows

Push this directory to your repository, with `dagflows.yaml` at its root, and create the workflow as shown in [Running an example](https://github.com/dagflows/examples#running-an-example-on-dagflows), steps 1 to 4. Then set the variables, before the deploy:

```bash
# 1. The discount and the gold tier, plain variables of the workflow
for pair in DISCOUNT_CENTS=500 GOLD_TIER_CENTS=10000; do
  jq -n --arg value "${pair#*=}" '{value: $value}' | curl -sS -X PUT "$API/api/v1/workflows/$WORKFLOW/variables/${pair%%=*}" \
    -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG" -H "Content-Type: application/json" \
    --data-binary @- | jq -c '.data | {name, scope, secret, version}'
done

# 2. The signing key, a secret of the project
REPORT_SIGNING_KEY=$(openssl rand -hex 32)
jq -n --arg value "$REPORT_SIGNING_KEY" '{value: $value, secret: true}' | curl -sS -X PUT "$API/api/v1/projects/$PROJECT/variables/REPORT_SIGNING_KEY" \
  -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG" -H "Content-Type: application/json" \
  --data-binary @- | jq -c '.data | {name, scope, secret, version}'
```

- A deploy fails if a node names a variable that neither the workflow, nor its project, nor its organization holds, and its progress says which node names which: `variables not set on the workflow, its project or its organization: node "apply_pricing" names DISCOUNT_CENTS`.
- A node gets the workflow's own value of a name, else its project's, else its organization's. The key is set on the project, so every workflow of the project that names it signs with the same key. An organization's variables are set by its admins, under `$API/api/v1/organizations/$ORG/variables/NAME`.
- `"secret": true`: The value is never shown again. `GET .../variables/REPORT_SIGNING_KEY` answers without it, while a plain variable's route gives its `value`. Both list, under `used_by`, the workflows whose running version names it and gets that value.

Then deploy as the guide's step 5 shows, and start a run with the orders as in [step 6](https://github.com/dagflows/examples/tree/main/06-trigger#run-on-dagflows). Read the logs as the guide shows:

```
INFO manual event <event_id> received at <received_at>
INFO run <workflow_run_id>: ingested 5 orders
time=<timestamp> level=INFO msg="validated orders" kept=3 rejected=2
INFO enriched 3 orders, gold from 10000 cents node=enrich_customers
INFO scored 5 orders node=score_risk
time=<timestamp> level=INFO msg="priced orders" scored=5 discounted=3 discount_cents=500
INFO report: 3 orders, 2 rejected, 43749 cents net of 1500 discount
INFO signed the report: <signature>
```

With the same key and orders, the signature is the one the local run printed.

## Changing a Value

A node reads its variables when it starts, so a new value reaches the next run without a deploy:

```bash
jq -n '{value: "700"}' | curl -sS -X PUT "$API/api/v1/workflows/$WORKFLOW/variables/DISCOUNT_CENTS" \
  -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG" -H "Content-Type: application/json" \
  --data-binary @- | jq -c '.data | {name, version}'
```

Start another run. `apply_pricing` logs `discount_cents=700` and the report reads `43149 cents net of 2100 discount`. A node that is already running keeps the values it started with.

## Keeping a Secret

- A secret's value is masked as `***` wherever a node that gets it prints it, in its log lines and in a failure's message. A value shorter than 8 bytes is not masked, since it would hide ordinary text.
- Masking catches accidents. A node can still print a secret encoded, so print none.
- A secret is stored sealed, and travels sealed to the worker that runs the node.
