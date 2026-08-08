# 玉置浩二 8/23大宮公演 チケット再販通知 - セットアップ手順

## 事前に知っておいてほしいこと

- 1分おきに動かすため、GitHubの「非公開リポジトリの無料実行時間(月2,000分)」はすぐに使い切ってしまいます。
  そのため **公開(Public)リポジトリ** として作成することを強く推奨します。
  コードには個人情報は含まれておらず、通知先(ntfyのトピック名)は GitHub Secrets に保存するので、
  リポジトリを公開しても他人にあなたの通知は届きません。
- 2026年8月23日18:00(日本時間)を過ぎると、スクリプトが自動的にチェックを停止します。

---

## STEP 1. ntfyアプリをインストールする

1. iPhoneで App Store から「ntfy」を検索してインストール
2. Macで https://ntfy.sh から Mac用アプリ、またはブラウザで https://ntfy.sh/app を開く
3. 好きなランダム文字列を考えて「トピック名」にする
   例: `tamaki-omiya-8f3k9x2p7q` のような、他人が推測できない長い文字列
4. iPhone・Mac両方のアプリで、そのトピック名を「購読(Subscribe)」する
   → これで、そのトピックに送られた通知が両方の端末に届くようになります

---

## STEP 2. GitHubアカウントを作成する

1. https://github.com にアクセスし、サインアップ
2. メールアドレス・ユーザー名・パスワードを設定して登録

---

## STEP 3. 新しいリポジトリを作成する

1. GitHubにログイン後、右上の「+」→「New repository」
2. Repository name: 例 `tamaki-omiya-watch`
3. **Public** を選択(理由は上記の通り)
4. 「Create repository」をクリック

---

## STEP 4. ファイルをアップロードする

作成したリポジトリのページで「Add file」→「Upload files」を選び、
以下の4つのファイル(私が作成したもの)をドラッグ&ドロップしてアップロードしてください。

- `check_tickets.py`
- `requirements.txt`
- `state.json`
- `.gitignore`
- `.github/workflows/check-tickets.yml`
  (フォルダごとアップロードする必要があるため、GitHubの画面上で
   「.github/workflows/check-tickets.yml」というパスになるようにアップロードしてください。
   うまくいかない場合は、まず `.github` フォルダを作る操作をGitHub上の「Create new file」で
   `​.github/workflows/check-tickets.yml` という名前のファイルを新規作成し、中身をコピペする方法が確実です)

アップロード後、「Commit changes」をクリックして保存します。

---

## STEP 5. GitHub Secretsにntfyのトピック名を登録する

1. リポジトリの「Settings」タブを開く
2. 左メニュー「Secrets and variables」→「Actions」
3. 「New repository secret」をクリック
4. Name: `NTFY_TOPIC`
5. Value: STEP1で決めたトピック名(例: `tamaki-omiya-8f3k9x2p7q`)
6. 「Add secret」で保存

---

## STEP 6. Personal Access Token (PAT) を発行する

これは、外部のcronサービスからGitHubの処理を1分おきに起動するために必要です。

1. GitHubの右上アイコン→「Settings」→ 左メニュー一番下「Developer settings」
2. 「Personal access tokens」→「Fine-grained tokens」→「Generate new token」
3. Token name: 例 `ticket-watch-trigger`
4. Expiration: 2026年8月末程度に設定
5. Repository access: 「Only select repositories」→ 先ほど作った `tamaki-omiya-watch` を選択
6. Permissions →「Repository permissions」→「Actions」を **Read and write** に設定
7. 「Generate token」をクリックし、表示されたトークン(`github_pat_...`)を必ずコピーして
   安全な場所に保存しておく(このページを閉じると二度と表示されません)

---

## STEP 7. cron-job.orgで1分おきの外部トリガーを設定する

1. https://cron-job.org でアカウント作成
2. ログイン後、「Create cronjob」
3. Title: 例 `tamaki-omiya-trigger`
4. Address (URL):
   ```
   https://api.github.com/repos/【あなたのGitHubユーザー名】/tamaki-omiya-watch/actions/workflows/check-tickets.yml/dispatches
   ```
5. 実行方式(Execution schedule)を「毎分(Every minute)」に設定
6. 「Advanced」を開き、以下を設定:
   - Request method: **POST**
   - Request body:
     ```json
     {"ref":"main"}
     ```
   - Request headers に以下を追加:
     ```
     Authorization: Bearer 【STEP6で発行したPAT】
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
     Content-Type: application/json
     ```
7. 保存して有効化(Enable)する

---

## STEP 8. 動作テスト

1. リポジトリの「Actions」タブを開く
2. 左側に「Check Tamaki Omiya Tickets」というワークフローが表示されているはず
3. 「Run workflow」ボタンから手動で一度実行してみる
4. 数十秒〜1分ほどで完了するので、ログを開いて
   「該当なし」といった出力が正常に出ていればOK
5. エラーが出た場合は、そのエラーメッセージを教えてください。一緒に直しましょう

---

## STEP 9. 8/23当日以降の後片付け

- 8月23日18:00(JST)を過ぎると、スクリプト自身が自動的に「監視終了」してチェックをスキップするようになります
- 無駄な実行を止めるため、当日中に cron-job.org のジョブを「Disable」にしておくことをおすすめします
- チケットが取れたら、リポジトリごと削除して問題ありません
