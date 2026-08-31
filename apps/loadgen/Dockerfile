FROM golang:1.25 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/puda-loadgen ./cmd/puda-loadgen

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/puda-loadgen /usr/local/bin/puda-loadgen
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/puda-loadgen"]
