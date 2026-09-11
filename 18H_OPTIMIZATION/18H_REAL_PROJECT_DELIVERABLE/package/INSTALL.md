# Modernized BANKING_CORE — Install & Run

Java 17+ (validated OpenJDK 26).

```bash
java -Dserver.port=8089 -jar modernized-subsystem-1.0.0-SNAPSHOT.jar
```

```bash
curl http://127.0.0.1:8089/api/health
curl http://127.0.0.1:8089/api/subsystem/components
```
