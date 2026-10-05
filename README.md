# Adaptive Multi-Fidelity Graph Query — v0.3

Research question: can graph queries use a fraction of the data while keeping aggregate
answers within an accuracy tolerance?

v0.1 is the original NumPy proof of concept: synthetic graph, fixed fidelity levels,
and a heuristic adaptive node-count controller. **All original source, CSV results,
figures, README and technical note are preserved unchanged in `v0.1/`.**

v0.2 introduced an exact-query foundation for Neo4j/Cypher and a dependency-free memory
backend. It does not yet migrate the approximate controller into Neo4j. The tiny
dataset tests correctness and teaches graph concepts; it is not a performance workload.

**Live validation completed on 2026-10-03:** Neo4j 2026.09.0 Enterprise
in Desktop 2.2.1. All nine tests passed, including repeated seeding and exact COUNT
comparison against memory. See `results/neo4j/tiny-counts.json` and `docs/verification.md`.
No plugins were required. No Neo4j performance benchmark was measured.

v0.3 adds a matched synthetic workload with real Neo4j fixed-fidelity COUNT queries,
NumPy answer validation, repeated warm-cache latency measurements and explicit
sampling preparation costs. The original v0.1 controller remains available unchanged;
the controller has not yet been migrated into Neo4j.

**v0.3 measured on 2026-10-05:** 50,000 nodes, 149,996 edge records, 20 repeats.
At 10% fidelity, the median combined COUNT query time was 13.05 ms versus 45.76 ms
for exact COUNT. Charging fresh sample preparation raised the approximate request
to 1,806.75 ms. Query-only savings therefore do not establish an online speedup.
All sampled counts matched NumPy. See [the measured report](docs/v03-benchmark.md).

## v0.3 synthetic benchmark

Install the optional dependencies:

```sh
python -m pip install -e ".[neo4j,experiments]"
```

After configuring the same Neo4j environment variables described below:

```sh
python -m graph_mf --backend neo4j benchmark --nodes 50000 --repeats 20 --warmups 2 --output results/local/my-neo4j-run
```

Offline fallback (experiment dependencies required, no server or Neo4j driver required):

```sh
python -m graph_mf --backend memory benchmark --nodes 50000 --repeats 20 --warmups 2 --output results/local/my-memory-run
```

Use a new output folder for each run; existing measurements are not overwritten.
Outputs: raw CSV, summary CSV, metadata JSON and an accuracy/latency figure.
The committed Neo4j run is in `results/neo4j/synthetic-50k-v03/`.

### 这一阶段在研究什么？

先建立同一份 50,000 节点合成图，计算所有 `country='FR'` 的节点数量，以及
两端都满足这个条件的边数量。这两个完整答案是 ground truth。

然后给每个节点生成一个 `[0, 1)` 的随机数，保存在 `sample` 属性里。
10% fidelity 使用 `sample < 0.10` 的节点；25% 使用 `sample < 0.25`，依此类推。
同一轮的各档位使用同一组随机数，因此样本是嵌套的，和原 v0.1 的随机种子一致。

- 节点估计 = 采样后的目标节点数量 / fidelity。
- 边估计 = 两端均被采样的目标边数量 / fidelity²。
- 误差 = |估计值 − 完整答案| / 完整答案。

本项目会把每次 Neo4j 得到的原始计数与 NumPy 的同一份样本比较，任何不一致
都会终止实验。100% 档位使用完整查询，并在每轮重新计时。

准备样本需要生成随机数、写回数据库、维护索引。这些费用在 CSV 里单独列出；
`query_ms` 只计算准备完毕后的两条 COUNT，`with_preparation_ms` 给每个近似档位
计入完整的一次准备费用。不能只看查询加速就声称整个流程更快。

### Workload and timing contract

The generator produces exactly the v0.1 country and endpoint arrays for the same seed.
`MFNode` and `MF_EDGE` isolate this workload from the three-person exercise. The
dataset identifier incorporates a SHA-256 graph fingerprint. Each stored v0.1 edge
record becomes one directed relationship with a distinct `edge_id`; parallel endpoint
pairs remain separate and are counted once, matching v0.1 aggregate semantics.
No reverse edges are inserted. Schema constraints and batched MERGE allow serial
imports to be rerun without duplication. Import can be resumed after failure; unrelated
datasets are never cleared. Do not concurrently import or change sample properties
for the same dataset during a benchmark.

Composite indexes cover `(dataset, country)` and `(dataset, country, sample)`.
Each repeat materializes a fresh Bernoulli rank vector in batches of 2,000 nodes.
Import time is recorded separately. Warm-up precedes the timed workload, and each
repeat shuffles the five fidelity levels using recorded seeds. Timing uses client wall
time for two sequential COUNT requests via the same driver API, including transaction
and connection overhead; it is not server execution time alone. Both queries are
timed independently as well as summed. Index plans are saved with EXPLAIN.

Each preparation is reused across four approximate levels in the experiment, but its
full cost is charged to every approximate row for a single-level request comparison.
Do not sum those charged rows to infer total experiment wall time. Exact rows are
charged zero preparation because the exact query does not require sample properties.
Memory timing excludes server/network costs and is not directly comparable to Neo4j.
This is one warm-cache run on one host; no cold-cache, energy or memory claim follows.

## Run immediately, without Neo4j

From this repository's root, with Python 3.10 or later:

```sh
python -m graph_mf --backend memory smoke
python -m graph_mf --backend memory count node_count
python -m graph_mf --backend memory count edge_count
python -m graph_mf --backend memory count city_count --city Paris
python -m graph_mf --backend memory count age_count --min-age 24
python -m unittest discover -s tests -v
```

Expected counts: **3 people, 2 directed FRIEND relationships, 1 person in Paris,
2 people aged at least 24.** Memory is the default backend. It evaluates the same
fixed predicates in Python; it does not interpret arbitrary Cypher.
JSON output names the actual backend. An explicit `--backend neo4j` never silently
falls back to memory. `neo4j_measured: false` means no Neo4j **benchmark** has been
measured by this CLI; `neo4j_query_executed` separately identifies real query execution.

## 学习第一步：Node、Label、Property、Relationship

我们的练习图：

```text
Bowen (24, Paris) ──FRIEND──> Alice (22, Lyon)
        │
        └──────────FRIEND──> Bob (27, Lille)
```

| 词 | 意义 | 本项目的例子 |
|---|---|---|
| Node（节点） | 一个独立实体 | Bowen 这个人 |
| Label（标签） | 节点所属类别；一个节点可以有多个标签 | `:Person` |
| Property（属性） | 保存的键值数据；节点和关系都可以有属性 | `name: 'Bowen'`、`age: 24` |
| Relationship（关系） | 连接两个节点的有方向、带类型的边 | `(b)-[:FRIEND]->(a)` |

```cypher
(p:Person {name: 'Bowen', age: 24, city: 'Paris'})
```

`p` 是当前查询里的临时变量，不是保存的名字。`:Person` 是 Label，花括号里
是 Properties。`FRIEND` 是关系类型，不是节点 Label。关系有方向；这里用箭头
表示 Bowen 指向 Alice，不自动添加反向边。

### 第一次创建数据（在 Neo4j Browser 中）

在专门的学习数据库里运行以下两条语句，每条单独执行。
`MERGE` 查找匹配对象，没有时才创建；重复运行这个练习不会重复创建同一个人。
`dataset` 属性把本项目数据和其他人的练习隔开。

```cypher
CREATE CONSTRAINT graph_mf_person_identity IF NOT EXISTS
FOR (p:Person) REQUIRE (p.dataset, p.id) IS UNIQUE;
```

```cypher
MERGE (b:Person {dataset: 'graph-mf-tiny-v02', id: 'bowen'})
SET b.name = 'Bowen', b.age = 24, b.city = 'Paris'
MERGE (a:Person {dataset: 'graph-mf-tiny-v02', id: 'alice'})
SET a.name = 'Alice', a.age = 22, a.city = 'Lyon'
MERGE (c:Person {dataset: 'graph-mf-tiny-v02', id: 'bob'})
SET c.name = 'Bob', c.age = 27, c.city = 'Lille'
MERGE (b)-[:FRIEND]->(a)
MERGE (b)-[:FRIEND]->(c);
```

### 第一次查询

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN p;
```

`MATCH` 找到符合模式的节点，`RETURN` 返回结果。然后查看属性：

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN p.name AS name, p.age AS age, p.city AS city
ORDER BY name;
```

第一条 exact COUNT 查询（完整计数，不采样）：

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN count(p) AS count;
```

结果应为 `3`。下面数关系，结果应为 `2`：

```cypher
MATCH (:Person {dataset: 'graph-mf-tiny-v02'})-[r:FRIEND]->(:Person {dataset: 'graph-mf-tiny-v02'})
RETURN count(r) AS count;
```

查看 Bowen 指向的朋友：

```cypher
MATCH (b:Person {dataset: 'graph-mf-tiny-v02', id: 'bowen'})-[:FRIEND]->(friend:Person)
RETURN friend.name AS friend;
```

在 Desktop 的 **Query** 页面选择本地实例和 `neo4j` 数据库，运行下面这条，
切到图形结果即可看到三个人和两条关系：

```cypher
MATCH (a:Person {dataset: 'graph-mf-tiny-v02'})-[r:FRIEND]->(b:Person {dataset: 'graph-mf-tiny-v02'})
RETURN a, r, b;
```

你现在可以先理解这三件事：节点保存人，关系保存连接，COUNT 返回完整数据的
确切数量。后续近似查询才会与 exact COUNT 这个 ground truth 比较误差。

## Use a real Neo4j database

Use Neo4j Desktop or an existing Neo4j 5.26+ database. Install the optional official
Python driver:

```sh
python -m pip install -e ".[neo4j]"
```

PowerShell configuration (replace the password):

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "your-local-password"
$env:NEO4J_DATABASE = "neo4j"
python -m graph_mf --backend neo4j seed
python -m graph_mf --backend neo4j count node_count
python -m graph_mf --backend neo4j smoke
```

Linux/macOS: set the same variables using `export NAME=value`.
`.env.example` is a configuration template; the Python CLI reads environment variables
and does **not** automatically load `.env`.

If Docker is already installed, copy `.env.example` to `.env`, replace its password,
then run `docker compose up -d`. Compose reads `.env`; set the same password in your
shell for the Python CLI. Visit `http://localhost:7474` for Neo4j Browser. Ports bind
only to localhost. The volume retains the database; restarting a volume with a new
password does not reset existing database credentials. Stop with `docker compose down`.

The seed command creates a unique `(dataset, id)` constraint and loads three Person
nodes and two FRIEND edges in one data transaction. It sets only fixture properties,
does not clear the database, and can be rerun serially without duplication. Use a
dedicated learning database; extra nodes or edges carrying the same dataset marker
affect these counts. `smoke` reads existing Neo4j data and does not seed automatically.

To run the opt-in live test (it seeds the fixture twice):

```powershell
$env:RUN_NEO4J_TESTS = "1"
python -m unittest discover -s tests -v
```

Without this opt-in, live tests are skipped. Adapter mock tests verify Python calls,
parameter handling and transaction structure; they do not validate Cypher on a server.

## Preserve and reproduce v0.1

The original files are under `v0.1/`, including `results/`, `figures/`, and
`report/technical_note.md`. `docs/v01-preservation.json` records original file hashes.
Compiled `__pycache__` files from the archive are ignored by Git.

Install its original dependencies with `python -m pip install -r v0.1/requirements.txt`.
To reproduce its 50,000-node experiment **without overwriting archived results**,
copy `v0.1/` outside the preserved folder first:

```powershell
New-Item -ItemType Directory -Path results/local -Force | Out-Null
Copy-Item -LiteralPath v0.1 -Destination results/local/v01-rerun -Recurse
python results/local/v01-rerun/run_experiment.py
```

On Linux/macOS, use `mkdir -p results/local`
and `cp -R v0.1 results/local/v01-rerun` before running the copied script.
New timings depend on the machine; they are Python/NumPy measurements.

## Structure and research limits

```text
graph_mf/data/tiny.json        shared fixture
graph_mf/cypher/               parameterized schema, seed and exact queries
graph_mf/backends.py           common backend contract and implementations
graph_mf/__main__.py           seed / count / smoke CLI
tests/                        offline, adapter, legacy and opt-in live tests
v0.1/                         unchanged original experiments and outputs
docs/                         provenance and verification record
```

v0.1 models stored edge pairs as undirected and can generate duplicate endpoint pairs.
The v0.2 learning fixture uses directed FRIEND relationships. They are separate workloads;
their counts and execution times should not be compared as a migration benchmark.
The v0.1 full-fidelity experiment reuses one exact-query timing across repeats. Its
controller estimates uncertainty, which is not a guarantee of actual relative error,
especially for rare predicates or repeated adaptive decisions.

The v0.3 results provide a first measured Neo4j fixed-fidelity baseline. They establish
neither a general latency improvement nor memory/energy savings. NSGA-II and a novel
adaptive algorithm are not implemented. Next milestones: reduce online sampling cost,
migrate and evaluate the adaptive controller, then broaden the workload and cache states.

Official references: [Neo4j Python driver](https://neo4j.com/docs/python-manual/current/),
[Cypher MERGE](https://neo4j.com/docs/cypher-manual/current/clauses/merge/).
