# 旁观与回放前端

L1 的离线回放以 HTML/Canvas 实现，模板随 Python 包发布，代码在 `src/bedwars_arena/replay/viewer.html`。用 `bedwars-arena replay-l1 <记录目录> --html <新文件.html>` 导出可单独打开的回放；不需要 Node.js、服务部署或网络；Node.js 仅供可选的界面逻辑测试。支持地图缩放、拖动和跟随玩家，并可通过时间轴标记或筛选列表定位事件。详细记录格式、控制和版本限制见 [P7 说明](../docs/l1/p7-replay.md)。
