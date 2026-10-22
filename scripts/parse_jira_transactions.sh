#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Monta a linha do tempo das execuções do agente por lead Jira.

Uso:
  bash scripts/parse_jira_transactions.sh [--issue-key OP-1234] [--format text|json|otlp] [arquivo ...]
  cat app.log | bash scripts/parse_jira_transactions.sh --format otlp

Download direto do Application Insights:
  bash scripts/parse_jira_transactions.sh --app-insights [--issue-key OP-1234] [--format otlp] [--save-to logs.json]
  bash scripts/parse_jira_transactions.sh --issue-key OP-1234  # consulta automática se nenhum arquivo for passado

Opções:
  --issue-key KEY        Filtra os eventos pela chave da issue (ex: OP-8989).
  --format FMT           Formato de saída: text (padrão), json ou otlp (OpenTelemetry traces).
  --app-insights         Habilita download de dados do Azure Application Insights via az cli.
  --app NAME_OR_GUID     Componente do Application Insights (padrão: $AZURE_APP_INSIGHTS_NAME ou osbjira-proj-development-appinsights-5763).
  --resource-group RG    Resource group do Application Insights (padrão: $AZURE_RESOURCE_GROUP ou rg-osb-jira-agent-dev).
  --time-range RANGE     Janela de tempo para consulta KQL (ex: 1h, 24h, 7d; padrão: 24h).
  --limit N              Quantidade máxima de registros a coletar (padrão: 50).
  --save-to FILE         Salva o JSON bruto retornado pelo Application Insights no arquivo indicado.
  -h, --help             Exibe esta mensagem de ajuda.

Use '-' como arquivo para ler de stdin. Requer jq (e az CLI para --app-insights).
USAGE
}

issue_key=""
output_format="text"
input_files=()
fetch_app_insights=false
app_insights_app="${APPLICATION_INSIGHTS_APP:-${AZURE_APP_INSIGHTS_NAME:-osbjira-proj-development-appinsights-5763}}"
resource_group="${AZURE_RESOURCE_GROUP:-rg-osb-jira-agent-dev}"
time_range="24h"
query_limit=50
save_file=""

while (($#)); do
    case "$1" in
        --issue-key)
            (($# >= 2)) || { usage >&2; exit 2; }
            issue_key=$2
            shift 2
            ;;
        --format)
            (($# >= 2)) || { usage >&2; exit 2; }
            output_format=$2
            shift 2
            ;;
        --app-insights|--fetch-app-insights|--download-app-insights)
            fetch_app_insights=true
            shift
            ;;
        --app|--app-insights-app)
            (($# >= 2)) || { usage >&2; exit 2; }
            app_insights_app=$2
            shift 2
            ;;
        -g|--resource-group)
            (($# >= 2)) || { usage >&2; exit 2; }
            resource_group=$2
            shift 2
            ;;
        --time-range|--offset|--timespan)
            (($# >= 2)) || { usage >&2; exit 2; }
            time_range=$2
            shift 2
            ;;
        --limit|--take)
            (($# >= 2)) || { usage >&2; exit 2; }
            query_limit=$2
            shift 2
            ;;
        --save-to|--output-file)
            (($# >= 2)) || { usage >&2; exit 2; }
            save_file=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            input_files+=("$@")
            break
            ;;
        *)
            input_files+=("$1")
            shift
            ;;
    esac
done

if [[ "$output_format" != "text" && "$output_format" != "json" && "$output_format" != "otlp" ]]; then
    printf 'Formato inválido: %s (use text, json ou otlp).\n' "$output_format" >&2
    exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
    printf 'Dependência ausente: jq. Instale jq e tente novamente.\n' >&2
    exit 127
fi

if ((${#input_files[@]} == 0)); then
    if [[ "$fetch_app_insights" == "true" ]]; then
        :
    elif [[ -t 0 ]]; then
        if [[ -n "$issue_key" ]]; then
            fetch_app_insights=true
        else
            printf 'Nenhum arquivo ou entrada informada. Especifique um arquivo, use --app-insights ou informe --issue-key.\n\n' >&2
            usage >&2
            exit 2
        fi
    else
        input_files=("-")
    fi
fi

events_file=$(mktemp)
trap 'rm -f "$events_file"' EXIT
line_sequence=0

parse_line() {
    local line=$1
    local normalized

    normalized=$(jq -cn \
        --arg line "$line" \
        --argjson sequence "$line_sequence" '
        def structured_pattern:
          "^(?<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(?:Z|[+-][0-9:]+)?)?.*\\[(?<tag>[A-Z][A-Z0-9_]*)\\]\\s*(?<payload>\\{.*\\})$";
        def generic_pattern:
          "^(?<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(?:Z|[+-][0-9:]+)?)?.*\\[(?<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\\]\\s+\\[(?<logger>[^]]+)\\]\\s+\\[transaction_id=(?<transaction_id>[^]]+)\\]\\s+(?<message>.*)$";
        ((try ($line | fromjson) catch null) // null) as $json_line
        | ((try ($line | capture(structured_pattern)) catch null) // null) as $structured
        | (if ($json_line | type) == "object" then
             $json_line
           elif $structured != null then
             try ($structured.payload | fromjson) catch null
           else
             null
           end) as $base
        | if ($base | type) == "object" then
            (if ($base.customDimensions | type) == "string" then
               (try ($base.customDimensions | fromjson) catch {})
             else
               ($base.customDimensions // {})
             end) as $dimensions
            | ($dimensions + $base) as $merged
            | ($merged.message // "") as $message
            | ((try ($message | capture(structured_pattern)) catch null) // null) as $message_log
            | (if $message_log != null then
                 (try ($message_log.payload | fromjson) catch {}) + $merged
               else
                 $merged
               end) as $record
            | {
                timestamp: ($record.timestamp // $record.time // $structured.timestamp),
                event_tag: ($record.event_tag // $record.eventTag // $structured.tag // $message_log.tag),
                issue_key: ($record.issue_key // $record.issueKey),
                issue_id: ($record.issue_id // $record.issueId),
                transaction_id: ([ $record.transaction_id, $record.correlation_id, $record.operation_Id, $record.operation_id ] | map(select(. != null and . != "")) | .[0] // null),
                source: $record.source,
                webhook_event: ($record.webhook_event // $record.webhookEvent),
                status: $record.status,
                status_code: ($record.status_code // $record.statusCode),
                success: $record.success,
                issue_type: ($record.issue_type // $record.issueType),
                has_comment: $record.has_comment,
                category: $record.category,
                reasoning: ($record.reasoning // null),
                actions_taken: (
                  if ($record.actions_taken | type) == "string" then
                    (try ($record.actions_taken | fromjson) catch [])
                  elif ($record.actions_taken | type) == "array" then
                    $record.actions_taken
                  else
                    ($record.actions_taken // [])
                  end
                ),
                duration_ms: ($record.duration_ms // $record.durationMs),
                run_id: ($record.run_id // $record.runId),
                level: $record.level,
                logger: $record.logger,
                message: ($record.message // $record.diagnostic),
                _sequence: $sequence
              }
          else
            ((try ($line | capture(generic_pattern)) catch null) // null) as $generic
            | if $generic == null then
                empty
              else
                {
                  timestamp: $generic.timestamp,
                  event_tag: "LOG_MESSAGE",
                  issue_key: null,
                  issue_id: null,
                  transaction_id: $generic.transaction_id,
                  source: null,
                  webhook_event: null,
                  status: null,
                  status_code: null,
                  success: null,
                  issue_type: null,
                  has_comment: null,
                  category: null,
                  actions_taken: [],
                  duration_ms: null,
                  run_id: null,
                  level: $generic.level,
                  logger: $generic.logger,
                  message: $generic.message,
                  _sequence: $sequence
                }
              end
          end
        ') || return 0

    if [[ -n "$normalized" && "$normalized" != "null" ]]; then
        printf '%s\n' "$normalized" >>"$events_file"
    fi
}

_process_input_source() {
    local src=$1
    if jq -e 'has("tables") and (.tables | type == "array")' "$src" >/dev/null 2>&1; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            parse_line "$line"
            line_sequence=$((line_sequence + 1))
        done < <(jq -c '
            .tables[0] as $t
            | ($t.columns | map(.name)) as $cols
            | $t.rows[]
            | [range(length) as $i | {($cols[$i]): .[$i]}]
            | add
        ' "$src")
    else
        while IFS= read -r line || [[ -n "$line" ]]; do
            parse_line "$line"
            line_sequence=$((line_sequence + 1))
        done <"$src"
    fi
}

read_input() {
    local input=$1

    if [[ "$input" == "-" ]]; then
        local stdin_tmp
        stdin_tmp=$(mktemp)
        cat > "$stdin_tmp"
        _process_input_source "$stdin_tmp"
        rm -f "$stdin_tmp"
        return
    fi

    if [[ ! -r "$input" ]]; then
        printf 'Não foi possível ler o arquivo: %s\n' "$input" >&2
        return 1
    fi

    _process_input_source "$input"
}

download_app_insights() {
    if ! command -v az >/dev/null 2>&1; then
        printf 'Dependência ausente: az (Azure CLI). Instale a CLI da Azure e tente novamente.\n' >&2
        exit 127
    fi

    local issue_filter=""
    if [[ -n "$issue_key" ]]; then
        issue_filter="| where (message contains \"[WEBHOOK_\" and message contains \"$issue_key\") or message contains \"Erro ao executar ferramenta\" or (message contains \"$issue_key\" and (message contains \"[WARNING]\" or message contains \"[ERROR]\"))"
    else
        issue_filter="| where message contains \"[WEBHOOK_\" or message contains \"Erro ao executar ferramenta\""
    fi

    local kql_query
    kql_query=$(cat <<KQL
traces
| where timestamp > ago(${time_range})
${issue_filter}
| extend eventTag = case(
    message contains "[WEBHOOK_RESULT]", "WEBHOOK_RESULT",
    message contains "[WEBHOOK_ACCEPTED_ASYNC]", "WEBHOOK_ACCEPTED_ASYNC",
    message contains "[WEBHOOK_RECEIVED]", "WEBHOOK_RECEIVED",
    message contains "Erro ao executar ferramenta", "TOOL_ERROR",
    message contains "[WARNING]", "WARNING",
    message contains "[ERROR]", "ERROR",
    "LOG"
  )
| extend payload = case(
    message contains "[WEBHOOK_", parse_json(extract(@"\[(?:WEBHOOK_RESULT|WEBHOOK_ACCEPTED_ASYNC|WEBHOOK_RECEIVED)\]\s+(\{.*\})", 1, message)),
    dynamic(null)
  )
| extend txId = coalesce(
    tostring(payload.transaction_id),
    extract(@"\[transaction_id=([a-f0-9]+)\]", 1, message),
    operation_Id
  )
| project timestamp, eventTag,
    transaction_id = txId,
    issue_key = coalesce(tostring(payload.issue_key), extract(@"\b([A-Z][A-Z0-9_]*-\d+)\b", 1, message)),
    source = tostring(payload.source),
    status = tostring(payload.status),
    statusCode = toint(payload.status_code),
    webhookEvent = tostring(payload.webhook_event),
    success = tostring(payload.success),
    category = tostring(payload.category),
    reasoning = tostring(payload.reasoning),
    actions_taken = payload.actions_taken,
    runId = tostring(payload.run_id),
    durationMs = todouble(payload.duration_ms),
    operation_Id,
    diagnostic = tostring(coalesce(payload.error_message, payload.reason)),
    message = trim(@"[\r\n\s]+", message)
| order by timestamp desc
| take ${query_limit}
KQL
    )

    printf 'Executando consulta KQL no Application Insights (%s / %s)...\n%s\n' "$app_insights_app" "$resource_group" "$kql_query" >&2

    local raw_output
    raw_output=$(az monitor app-insights query \
        --app "$app_insights_app" \
        --resource-group "$resource_group" \
        --offset "$time_range" \
        --analytics-query "$kql_query" \
        --output json 2>/dev/null) || {
        printf 'Falha ao executar consulta no Application Insights (%s / %s).\n' "$app_insights_app" "$resource_group" >&2
        exit 1
    }

    if [[ -n "$save_file" ]]; then
        printf '%s\n' "$raw_output" > "$save_file"
        printf 'Dados brutos do Application Insights salvos em: %s\n' "$save_file" >&2
    fi

    local row_count
    row_count=$(jq -r '.tables[0].rows | length // 0' <<<"$raw_output" 2>/dev/null || echo 0)
    printf 'Registros obtidos do Application Insights: %s\n\n' "$row_count" >&2

    local tmp_ai_file
    tmp_ai_file=$(mktemp)
    printf '%s\n' "$raw_output" > "$tmp_ai_file"
    _process_input_source "$tmp_ai_file"
    rm -f "$tmp_ai_file"
}

if [[ "$fetch_app_insights" == "true" ]]; then
    download_app_insights
fi

for input_file in "${input_files[@]}"; do
    read_input "$input_file"
done

build_json_tree() {
    jq -s --arg issue_key "$issue_key" -f /dev/stdin "$events_file" <<'JQ'
def event_order: sort_by([(.timestamp // ""), (._sequence // 0)]);
def public_event: del(._sequence);
def attach_transactions($events):
  reduce ($events | event_order)[] as $ev (
    {current_tx: null, list: []};
    (if ($ev.transaction_id != null and $ev.transaction_id != "") then
       $ev.transaction_id
     else
       .current_tx
     end) as $tx
    | {
        current_tx: (if $ev.event_tag == "WEBHOOK_RESULT" then null else $tx end),
        list: (.list + [ $ev + {transaction_id: ($ev.transaction_id // $tx)} ])
      }
  ) | .list;
def summarize($events):
  ([ $events[] | select(.event_tag == "WEBHOOK_RESULT") ] | if length > 0 then .[-1] else $events[-1] end) as $last
  | {
      status: $last.status,
      status_code: $last.status_code,
      category: $last.category,
      reasoning: $last.reasoning,
      duration_ms: $last.duration_ms,
      run_id: $last.run_id,
      actions_taken: ($last.actions_taken // []),
      tool_errors: ([ $events[] | select(.event_tag == "TOOL_ERROR" or (.message != null and (.message | contains("Erro ao executar ferramenta")))) | .message ] | unique)
    };
.
| . as $raw_input
| [ $raw_input[]
    | . + {
        issue_key: (if .issue_key == "" then null else .issue_key end),
        transaction_id: (if .transaction_id == "" then null else .transaction_id end)
      }
  ] as $events
| ([ $events[] | select(.issue_key != null) | .issue_key ] | unique) as $keys
| {
    issues: [
      $keys[] as $key
      | select($issue_key == "" or ($key | ascii_downcase) == ($issue_key | ascii_downcase))
      | ($events | map(select(.issue_key == $key))) as $direct_raw
      | attach_transactions($direct_raw) as $direct
      | ([ $direct[] | select(.transaction_id != null) | .transaction_id ] | unique) as $transaction_ids
      | ([ $transaction_ids[] as $transaction_id
           | $events[] | select(.transaction_id == $transaction_id)
         ] | unique_by(._sequence)) as $transaction_events
      | (($direct + $transaction_events) | unique_by(._sequence) | event_order) as $timeline_pre
      | (if ($timeline_pre | length) > 0 then
           ($timeline_pre[0].timestamp // "") as $t_start
           | ($timeline_pre[-1].timestamp // "") as $t_end
           | ([ $events[] | select(.issue_key == null and .event_tag == "TOOL_ERROR" and .timestamp >= $t_start and .timestamp <= $t_end) ]) as $matched_tools
           | (($timeline_pre + $matched_tools) | unique_by(._sequence) | event_order)
         else
           $timeline_pre
         end) as $timeline
      | {
          issue_key: $key,
          first_seen: $timeline[0].timestamp,
          last_seen: $timeline[-1].timestamp,
          status: ([ $timeline[] | select(.status != null) | .status ] | .[-1] // null),
          category: ([ $timeline[] | select(.category != null and .category != "") | .category ] | .[-1] // null),
          event_count: ($timeline | length),
          uncorrelated_event_count: ([ $timeline[] | select(.transaction_id == null) ] | length),
          events: [ $timeline[] | public_event ],
          transactions: [
            $transaction_ids[] as $transaction_id
            | ([ $direct[] | select(.transaction_id == $transaction_id) ] | event_order) as $direct_run
            | ($direct_run[0].timestamp // "") as $r_start
            | ($direct_run[-1].timestamp // "") as $r_end
            | ([ $timeline[] | select(.transaction_id == $transaction_id or (.event_tag == "TOOL_ERROR" and .timestamp >= $r_start and .timestamp <= $r_end)) ] | event_order) as $run
            | {
                transaction_id: $transaction_id,
                started_at: $run[0].timestamp,
                finished_at: $run[-1].timestamp,
                source: ([ $run[] | select(.source != null) | .source ] | .[0] // null),
                webhook_event: ([ $run[] | select(.webhook_event != null) | .webhook_event ] | .[0] // null)
              }
              + summarize($run)
              + {events: [ $run[] | public_event ]}
          ] | sort_by([(.started_at // ""), .transaction_id])
        }
    ] | sort_by(.issue_key),
    unassigned_events: [
      $events[] as $event
      | select($event.issue_key == null)
      | select(
          $event.transaction_id == null
          or ([ $events[] | select(.transaction_id == $event.transaction_id and .issue_key != null) ] | length == 0)
        )
      | $event
      | public_event
    ] | event_order
  }
JQ
}

if [[ "$output_format" == "json" ]]; then
    build_json_tree
    exit $?
fi

if [[ "$output_format" == "otlp" ]]; then
    build_json_tree | jq '
def hex_digit: ["0","1","2","3","4","5","6","7","8","9","a","b","c","d","e","f"];
def hash_hex(str; len):
  reduce (str | explode)[] as $b (2166136261; ((. * 16777619) + $b) % 4294967296) as $h1
  | reduce (str | explode | reverse)[] as $b (16777619; ((. * 2166136261) + $b) % 4294967296) as $h2
  | [
      ($h1 / 268435456 | floor % 16), ($h1 / 16777216 | floor % 16), ($h1 / 1048576 | floor % 16), ($h1 / 65536 | floor % 16),
      ($h1 / 4096 | floor % 16), ($h1 / 256 | floor % 16), ($h1 / 16 | floor % 16), ($h1 % 16),
      ($h2 / 268435456 | floor % 16), ($h2 / 16777216 | floor % 16), ($h2 / 1048576 | floor % 16), ($h2 / 65536 | floor % 16),
      ($h2 / 4096 | floor % 16), ($h2 / 256 | floor % 16), ($h2 / 16 | floor % 16), ($h2 % 16)
    ] | map(hex_digit[.]) | join("") | (if len == 32 then (. + (explode | reverse | implode)) else (explode[0:len] | implode) end);

def to_unix_nano(ts; offset_ms):
  if ts == null or ts == "" then
    "0"
  else
    (try (ts | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) catch 0) as $secs
    | ((try (ts | capture("\\.(?<ms>[0-9]{3})") | .ms | tonumber) catch 0) // 0) as $ms
    | (($secs * 1000) + $ms + (offset_ms // 0) | floor) as $total_ms
    | "\($total_ms)000000"
  end;

def normalize_trace_id(id; fallback):
  if (id != null and (id | test("^[0-9a-fA-F]{32}$"))) then
    (id | ascii_downcase)
  else
    hash_hex(fallback; 32)
  end;

def otel_attr(k; v):
  if v == null or v == "" then empty
  elif (v | type) == "string" then {key: k, value: {stringValue: v}}
  elif (v | type) == "number" then
    if (v | floor) == v then {key: k, value: {intValue: (v | tostring)}}
    else {key: k, value: {doubleValue: v}} end
  elif (v | type) == "boolean" then {key: k, value: {boolValue: v}}
  elif (v | type) == "array" then {key: k, value: {stringValue: (v | join("; "))}}
  else {key: k, value: {stringValue: (v | tostring)}} end;

. as $doc
| {
    resourceSpans: [
      {
        resource: {
          attributes: [
            {key: "service.name", value: {stringValue: "osb-jira-agent"}},
            {key: "service.namespace", value: {stringValue: "jira"}},
            {key: "telemetry.sdk.language", value: {stringValue: "python"}},
            {key: "telemetry.sdk.name", value: {stringValue: "opentelemetry"}}
          ]
        },
        scopeSpans: [
          {
            scope: {
              name: "jira-agent.transactions",
              version: "1.0.0"
            },
            spans: [
              $doc.issues[] as $issue
              | (
                  # Transactions with correlated events
                  ($issue.transactions // [])[] as $tx
                  | normalize_trace_id($tx.transaction_id; $issue.issue_key + "-" + $tx.transaction_id) as $trace_id
                  | hash_hex("span-root-" + $tx.transaction_id; 16) as $root_span_id
                  | (
                      # Root Span for Transaction
                      {
                        traceId: $trace_id,
                        spanId: $root_span_id,
                        parentSpanId: "",
                        name: ("Jira Lead " + $issue.issue_key + " (Execução " + ($tx.transaction_id[0:8]) + ")"),
                        kind: 2,
                        startTimeUnixNano: to_unix_nano($tx.started_at; 0),
                        endTimeUnixNano: to_unix_nano($tx.finished_at; ($tx.duration_ms // 100)),
                        attributes: [
                          otel_attr("jira.issue_key"; $issue.issue_key),
                          otel_attr("jira.transaction_id"; $tx.transaction_id),
                          otel_attr("jira.status"; $tx.status),
                          otel_attr("http.status_code"; $tx.status_code),
                          otel_attr("duration_ms"; $tx.duration_ms),
                          otel_attr("gen_ai.run_id"; $tx.run_id),
                          otel_attr("actions_taken"; $tx.actions_taken)
                        ],
                        status: (if $tx.status == "failed" then {code: 2, message: "Error"} else {code: 1} end)
                      },
                      # Child Spans for Events inside Transaction
                      ($tx.events // [])[] as $ev
                      | {
                          traceId: $trace_id,
                          spanId: hash_hex("span-" + ($ev.timestamp // "") + "-" + ($ev.event_tag // ""); 16),
                          parentSpanId: $root_span_id,
                          name: ($ev.event_tag // "EVENT"),
                          kind: 1,
                          startTimeUnixNano: to_unix_nano($ev.timestamp; 0),
                          endTimeUnixNano: to_unix_nano($ev.timestamp; ($ev.duration_ms // 50)),
                          attributes: [
                            otel_attr("jira.issue_key"; $issue.issue_key),
                            otel_attr("event.tag"; $ev.event_tag),
                            otel_attr("jira.status"; $ev.status),
                            otel_attr("http.status_code"; $ev.status_code),
                            otel_attr("duration_ms"; $ev.duration_ms),
                            otel_attr("source"; $ev.source),
                            otel_attr("gen_ai.run_id"; $ev.run_id),
                            otel_attr("actions_taken"; $ev.actions_taken)
                          ],
                          status: (if $ev.status == "failed" then {code: 2, message: "Error"} else {code: 1} end)
                        }
                    ),
                  # Standalone / uncorrelated events for this issue
                  ($issue.events // [])[] as $ev
                  | select($ev.transaction_id == null)
                  | normalize_trace_id($ev.run_id; "uncorrelated-" + $issue.issue_key + "-" + ($ev.timestamp // "")) as $trace_id
                  | {
                      traceId: $trace_id,
                      spanId: hash_hex("span-standalone-" + ($ev.timestamp // "") + "-" + ($ev.event_tag // ""); 16),
                      parentSpanId: "",
                      name: ($ev.event_tag + " (" + $issue.issue_key + ")"),
                      kind: 1,
                      startTimeUnixNano: to_unix_nano($ev.timestamp; 0),
                      endTimeUnixNano: to_unix_nano($ev.timestamp; ($ev.duration_ms // 50)),
                      attributes: [
                        otel_attr("jira.issue_key"; $issue.issue_key),
                        otel_attr("event.tag"; $ev.event_tag),
                        otel_attr("jira.status"; $ev.status),
                        otel_attr("http.status_code"; $ev.status_code),
                        otel_attr("duration_ms"; $ev.duration_ms),
                        otel_attr("source"; $ev.source),
                        otel_attr("gen_ai.run_id"; $ev.run_id),
                        otel_attr("actions_taken"; $ev.actions_taken)
                      ],
                      status: (if $ev.status == "failed" then {code: 2, message: "Error"} else {code: 1} end)
                    }
                )
            ]
          }
        ]
      }
    ]
  }
'
    exit $?
fi

jq -sr --arg issue_key "$issue_key" -f /dev/stdin "$events_file" <<'JQ'
def event_order: sort_by([(.timestamp // ""), (._sequence // 0)]);
def attach_transactions($events):
  reduce ($events | event_order)[] as $ev (
    {current_tx: null, list: []};
    (if ($ev.transaction_id != null and $ev.transaction_id != "") then
       $ev.transaction_id
     else
       .current_tx
     end) as $tx
    | {
        current_tx: (if $ev.event_tag == "WEBHOOK_RESULT" then null else $tx end),
        list: (.list + [ $ev + {transaction_id: ($ev.transaction_id // $tx)} ])
      }
  ) | .list;
.
| . as $raw_input
| [ $raw_input[]
    | . + {
        issue_key: (if .issue_key == "" then null else .issue_key end),
        transaction_id: (if .transaction_id == "" then null else .transaction_id end)
      }
  ] as $events
| ([ $events[] | select(.issue_key != null) | .issue_key ] | unique) as $keys
| ([ $keys[] | select($issue_key == "" or (ascii_downcase == ($issue_key | ascii_downcase))) ] | length) as $matching_count
| (if $matching_count == 0 then
    ["Nenhuma issue encontrada nos logs estruturados."]
  else
    [
      $keys[] as $key
      | select($issue_key == "" or ($key | ascii_downcase) == ($issue_key | ascii_downcase))
      | ($events | map(select(.issue_key == $key))) as $direct_raw
      | attach_transactions($direct_raw) as $direct
      | ([ $direct[] | select(.transaction_id != null and .transaction_id != "") | .transaction_id ] | unique) as $transaction_ids
      | ([ $transaction_ids[] as $transaction_id
           | $events[] | select(.transaction_id == $transaction_id)
         ] | unique_by(._sequence)) as $transaction_events
      | (($direct + $transaction_events) | unique_by(._sequence) | event_order) as $timeline_pre
      | (if ($timeline_pre | length) > 0 then
           ($timeline_pre[0].timestamp // "") as $t_start
           | ($timeline_pre[-1].timestamp // "") as $t_end
           | ([ $events[] | select(.issue_key == null and .event_tag == "TOOL_ERROR" and .timestamp >= $t_start and .timestamp <= $t_end) ]) as $matched_tools
           | (($timeline_pre + $matched_tools) | unique_by(._sequence) | event_order)
         else
           $timeline_pre
         end) as $timeline
      | ([ $timeline[] | select(.status != null) | .status ] | .[-1] // "indisponível") as $status
      | ([ $timeline[] | select(.category != null and .category != "") | .category ] | .[-1] // "") as $category
      | ([
          "Lead " + $key
          + (if $category != "" then " [Categoria: " + $category + "]" else "" end)
          + " | eventos=" + (($timeline | length) | tostring)
          + " | execuções correlacionadas=" + (($transaction_ids | length) | tostring)
          + " | status mais recente=" + $status,
          ($timeline[] as $event
           | ([ $event.webhook_event, $event.status, $event.source, (if $event.event_tag == "TOOL_ERROR" then $event.message else empty end) ]
              | map(select(. != null and . != ""))
              | join(", ")) as $details
           | "  " + ($event.timestamp // "-") + " " + $event.event_tag
             + " (" + (if $details == "" then "sem detalhes" else $details end)
             + "; " + ($event.transaction_id // "sem transaction_id") + ")"),
          ($transaction_ids[] as $transaction_id
           | ([ $direct[] | select(.transaction_id == $transaction_id) ] | event_order) as $direct_run
           | ($direct_run[0].timestamp // "") as $r_start
           | ($direct_run[-1].timestamp // "") as $r_end
           | ([ $timeline[] | select(.transaction_id == $transaction_id or (.event_tag == "TOOL_ERROR" and .timestamp >= $r_start and .timestamp <= $r_end)) ] | event_order) as $run
           | ([ $run[] | select(.event_tag == "WEBHOOK_RESULT") ] | if length > 0 then .[-1] else $run[-1] end) as $last
           | ([ $run[] | select(.event_tag == "TOOL_ERROR" or (.message != null and (.message | contains("Erro ao executar ferramenta")))) | .message ] | unique) as $tool_errors
           | ([
                "  Execução " + $transaction_id + ": "
                + ($last.status // "em andamento/sem resultado")
                + (if $last.category != null and $last.category != "" then " [Categoria: " + $last.category + "]" else "" end)
                + " (" + (if $last.status_code == null then "sem status HTTP" else ($last.status_code | tostring) end)
                + "), duração=" + (if $last.duration_ms == null then "n/d" else ($last.duration_ms | tostring) end) + " ms",
                (if $last.reasoning != null and $last.reasoning != "" then
                   "    Raciocínio: " + $last.reasoning
                 else empty end),
                ($last.actions_taken[]? | "    - " + tostring),
                ($tool_errors[]? | "    ALERTA FERRAMENTA: " + tostring)
              ] | join("\n")))
        ] | join("\n"))
    ]
  end)
  + (if ([ $events[] | select(.issue_key == null) ] | length) > 0 then
     ["Eventos sem issue associada: " + ([ $events[] | select(.issue_key == null) ] | length | tostring)]
   else [] end)
| join("\n\n")
JQ
