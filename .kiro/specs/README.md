# Kiro specs

このdirectoryはAthenaのfeature specとimplementation evidenceを保持する.

## Authority

- Current observable behaviorの正本はcodeとtestである.
- ADRは横断的で長期的なarchitecture decisionの正本である.
- feature specはrequirements、design、research、implementation historyの正本である.
- Backlogの正本は[roadmap](../steering/roadmap.md)とactive specである.
- TODO.mdはbacklog authorityではない. durable itemはroadmapまたはfeature specへ移管して追跡する.

## Lifecycle

- active: 実装中または次に実装するspec. `spec.json`、`tasks.md`、implementation evidenceをcurrent instructionとして扱う.
- completed: 実装済みfeatureのhistorical evidence. 完了済みspecは削除せず、当時のpathや判断を履歴として保持する.
- superseded: 後継specやADRへ置き換え済みのspec. 後継のownerを明記し、旧内容をcurrent instructionにしない.
- abandoned: durable requirementを持たない破棄済みdraft. 削除は個別確認後に行い、一括cleanup対象にしない.

## Current vs historical path

active/current specだけをcurrent instructionとして扱う. completed specはhistorical evidenceなので、
旧pathや旧commandが残っていても、それ自体ではcurrent guidanceではない. current docs、root task
interface、validation policy、active specが古いpathを指す場合だけstale pathとして修正する.

`monorepo-migration` は現在のactive specであり、phase、task completion、implementation evidenceは
[tasks.md](monorepo-migration/tasks.md)を正本にする.
