module github.com/tiddly-data-converter/bridge

go 1.25.9

require (
	github.com/tiddly-data-converter/canon v0.0.0-00010101000000-000000000000
	github.com/tiddly-data-converter/ingesta v0.0.0
)

require golang.org/x/text v0.36.0 // indirect

replace (
	github.com/tiddly-data-converter/canon => ../canon
	github.com/tiddly-data-converter/ingesta => ../ingesta
)
