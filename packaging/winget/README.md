# winget 提交流程

发版后 CI 会把填好版本号与 SHA256 的 manifest 打成 `winget-manifests.zip` 挂在 Release 资产里。

提交：解压，把 `manifests/k/KaliLeo/InterestModel/<版本>/` 目录原样放进 [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) 的 fork，开 PR。首个版本经微软人工审核，之后每版重复同一步骤。

本地验证：`winget validate <目录>`，`winget install --manifest <目录>`。
