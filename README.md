# OpenDART 고유번호 다운로드

OpenDART `corpCode.xml` API를 호출해 DART에 등록된 공시대상회사의 고유번호, 회사명, 종목코드, 최근변경일자를 CSV 파일로 저장하는 간단한 Python 스크립트입니다.

## 준비

1. OpenDART에서 API 인증키를 발급받습니다.
2. Python 3.9 이상을 준비합니다. 별도 패키지 설치 없이 표준 라이브러리만 사용합니다.



## 먼저 파일 3개를 PC로 다운로드하는 방법

이 저장소에 있는 3개 파일은 OpenDART에서 내려받는 데이터 파일이 아니라, CSV를 만들기 위해 내 PC에 받아야 하는 준비 파일입니다. 가장 쉬운 방법은 GitHub 화면에서 파일을 직접 내려받는 것입니다.

### 방법 1: GitHub에서 ZIP으로 한 번에 받기

1. GitHub에서 이 프로젝트 저장소 또는 PR 화면을 엽니다.
2. 초록색 **Code** 버튼을 누릅니다.
3. **Download ZIP**을 누릅니다.
4. 내려받은 ZIP 파일의 압축을 풉니다.
5. 압축을 푼 폴더 안에 아래 3개 파일이 있는지 확인합니다.

   ```text
   .gitignore
   README.md
   download_dart_corp_codes.py
   ```

6. VS Code에서 **File > Open Folder...**를 누르고, 방금 압축을 푼 폴더를 선택합니다.

### 방법 2: GitHub에서 파일 하나씩 받기

1. GitHub에서 `download_dart_corp_codes.py` 파일을 클릭합니다.
2. 오른쪽 위 **Raw** 버튼을 누릅니다.
3. 열린 화면에서 마우스 오른쪽 버튼을 누르고 **다른 이름으로 저장**을 선택합니다.
4. 파일 이름을 반드시 `download_dart_corp_codes.py`로 저장합니다.
5. 같은 방법으로 `README.md`, `.gitignore`도 저장합니다.
6. 세 파일을 같은 폴더에 넣은 뒤 VS Code에서 그 폴더를 엽니다.

> 실제로 DART 회사목록 CSV를 다운로드하는 파일은 실행 후 생성되는 `dart_corp_codes.csv`입니다. 즉, 위 3개 파일을 먼저 PC에 받은 다음 `download_dart_corp_codes.py`를 실행해야 CSV가 생깁니다.


## GitHub에서 파일이 안 보일 때

이 파일들이 내 PC나 작업 환경에는 있지만 GitHub 사이트에서 보이지 않는다면, 아직 GitHub 원격 저장소로 `push`되지 않은 상태일 수 있습니다. Git은 보통 아래 두 단계가 모두 끝나야 GitHub 웹사이트에서 파일을 확인할 수 있습니다.

1. `git commit`: 내 컴퓨터의 Git 기록에 저장합니다.
2. `git push`: GitHub 원격 저장소에 업로드합니다.

VS Code 터미널에서 현재 브랜치와 원격 저장소가 있는지 확인합니다.

```bash
git branch --show-current
git remote -v
```

`git remote -v` 결과가 비어 있으면 GitHub 업로드 위치가 아직 연결되지 않은 것입니다. 이 경우 GitHub에서 저장소를 만든 뒤 안내되는 원격 저장소 주소를 연결해야 합니다.

```bash
git remote add origin https://github.com/사용자명/저장소명.git
git push -u origin HEAD
```

이미 `origin`이 있다면 아래 명령으로 현재 브랜치를 GitHub에 올립니다.

```bash
git push -u origin HEAD
```

업로드 후 GitHub 웹사이트에서 현재 브랜치를 선택하면 `.gitignore`, `README.md`, `download_dart_corp_codes.py` 파일을 찾을 수 있습니다.

## 파일 설명

| 파일 | VS Code에서 필요한 이유 |
| --- | --- |
| `download_dart_corp_codes.py` | 실제로 OpenDART API를 호출해서 CSV 파일을 만드는 Python 실행 파일입니다. |
| `README.md` | 실행 방법을 설명하는 문서입니다. VS Code에서는 미리보기로 열어 보면서 따라 하면 됩니다. |
| `.gitignore` | 실행 후 생성되는 CSV와 Python 캐시 파일이 Git에 올라가지 않도록 제외하는 설정 파일입니다. 직접 실행할 필요는 없습니다. |


### VS Code에서 가장 빠르게 실행하는 방법

`download_dart_corp_codes.py` 파일을 더블클릭해서 여는 것만으로는 CSV가 다운로드되지 않습니다. VS Code 아래쪽 터미널에 명령어를 입력해서 실행해야 합니다.

1. VS Code에서 이 폴더를 엽니다.
2. 상단 메뉴에서 **Terminal > New Terminal**을 누릅니다.
3. 터미널에 아래 명령어 중 하나를 복사해서 붙여넣습니다.

Windows PowerShell이면:

```powershell
python download_dart_corp_codes.py --api-key "발급받은_인증키" -o dart_corp_codes.csv
```

macOS 또는 Linux이면:

```bash
python3 download_dart_corp_codes.py --api-key "발급받은_인증키" -o dart_corp_codes.csv
```

4. 실행이 끝나면 왼쪽 Explorer에 `dart_corp_codes.csv` 파일이 생깁니다. 그 파일이 다운로드 결과입니다.

만약 `python` 또는 `python3` 명령을 찾을 수 없다는 오류가 나오면 Python을 설치한 뒤 VS Code를 다시 열어 실행합니다.

## VS Code에서 실행하기

1. VS Code를 열고 **File > Open Folder...** 메뉴에서 이 폴더를 엽니다.
2. 왼쪽 Explorer에서 `download_dart_corp_codes.py` 파일이 보이는지 확인합니다.
3. VS Code 상단 메뉴에서 **Terminal > New Terminal**을 클릭해 터미널을 엽니다.
4. 터미널 위치가 이 프로젝트 폴더인지 확인합니다. 터미널에 아래 명령을 입력했을 때 `download_dart_corp_codes.py`가 보여야 합니다.

   ```bash
   ls
   ```

5. OpenDART 인증키를 환경변수로 설정합니다.

   macOS 또는 Linux 터미널:

   ```bash
   export OPENDART_API_KEY="발급받은_인증키"
   ```

   Windows PowerShell 터미널:

   ```powershell
   $env:OPENDART_API_KEY="발급받은_인증키"
   ```

6. 상장회사 목록 CSV를 생성합니다.

   ```bash
   python3 download_dart_corp_codes.py -o dart_corp_codes.csv
   ```

   Windows에서 `python3` 명령이 동작하지 않으면 아래처럼 `python`으로 실행합니다.

   ```powershell
   python download_dart_corp_codes.py -o dart_corp_codes.csv
   ```

7. 실행이 끝나면 Explorer에 `dart_corp_codes.csv` 파일이 생깁니다. 파일을 클릭하면 VS Code에서 바로 열 수 있습니다.

비상장회사까지 포함한 전체 공시대상회사 목록이 필요하면 아래 명령을 실행합니다.

```bash
python3 download_dart_corp_codes.py --include-unlisted -o dart_all_corp_codes.csv
```

Windows에서 `python3` 대신 `python`을 써야 하는 환경이면 아래처럼 실행합니다.

```powershell
python download_dart_corp_codes.py --include-unlisted -o dart_all_corp_codes.csv
```

## 사용법

환경변수로 인증키를 지정한 뒤 실행합니다.

```bash
export OPENDART_API_KEY="발급받은_인증키"
python3 download_dart_corp_codes.py -o dart_corp_codes.csv
```

또는 인증키를 인자로 직접 전달할 수 있습니다.

```bash
python3 download_dart_corp_codes.py --api-key "발급받은_인증키" --output dart_corp_codes.csv
```

기본 동작은 `stock_code`가 있는 상장회사만 CSV로 저장합니다. 비상장 등 종목코드가 비어 있는 공시대상회사까지 모두 저장하려면 `--include-unlisted` 옵션을 추가합니다.

```bash
python3 download_dart_corp_codes.py --include-unlisted -o dart_all_corp_codes.csv
```

## 출력 컬럼

| 컬럼 | 설명 |
| --- | --- |
| `corp_code` | DART 공시대상회사의 8자리 고유번호 |
| `corp_name` | 회사명 |
| `stock_code` | 종목코드. 비상장 등 일부 회사는 값이 비어 있을 수 있습니다. |
| `modify_date` | 최근변경일자 |

CSV는 Excel에서 한글이 깨지지 않도록 `utf-8-sig` 인코딩으로 저장합니다.

## 참고

OpenDART 개발가이드 기준 고유번호 API는 `GET https://opendart.fss.or.kr/api/corpCode.xml` 요청에 `crtfc_key` 인증키를 전달하면 ZIP 파일을 반환합니다.
