FROM python:3.12.8-slim-bookworm

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y chromium chromium-driver
COPY requirements.txt .
RUN pip3 install -r requirements.txt
COPY . .
#COPY job_search.py .
#COPY utils/ ./utils/
COPY .env .
RUN ls

CMD ["python3", "-u", "job_search.py", "all"]
