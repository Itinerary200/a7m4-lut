# CI 工作流(暂未启用)

GitHub 拒绝推送 .github/workflows/* 是因为当前 gh 的 token 没有 \workflow\ scope。
要用它,先补权限:

    gh auth refresh -s workflow

然后把本文件拷回去:

    mkdir .github\workflows
    copy tools\ci\quality.yml .github\workflows\

再提交推送即可。工作流本身跑的是 ruff / mypy / pytest 三道门禁。
