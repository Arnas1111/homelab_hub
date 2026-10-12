FROM python:3.12-slim
WORKDIR /opt/control
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY control ./control
COPY static ./static
ENV CONTROL_DATA=/data
EXPOSE 8080
CMD ["uvicorn", "control.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
