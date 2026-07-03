"""L3 端到端/UAT 业务场景测试包 —— Rule 10.1 第三层。

与 tests/integration/(L2,验证"组件是否真的接线")不同,本包验证"一个完整的
业务叙事,在真实依赖(真实 Neo4j 容器、真实 SQLite 状态库、真实 SOP 引擎)下
是否真的按预期发生"。

⚠️ 重要边界说明(写在这里而不是藏起来):本仓库目前没有任何 FastAPI/uvicorn
主入口把 AgentOSKernel.wake_up()、SOPEngine、Feishu webhook 回调、MCP
Governance Gateway 接成一个可对外提供服务的常驻进程(全仓库搜索
FastAPI app / main.py 均无结果)。因此本包里的"真实环境模拟"能做到的
最高集成边界,是直接驱动这些组件的 Python 组合根(composition root)——
即 scripts/run_uat.py 已经在用的模式 —— 而不是通过一个真实 HTTP 服务器
发请求。这个边界本身就是本次验证的发现之一,详见测试报告。
"""
