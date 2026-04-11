module github.com/tiddly-data-converter/bridge

go 1.24

require (
	github.com/tiddly-data-converter/canon   v0.0.0
	github.com/tiddly-data-converter/ingesta v0.0.0
)

replace (
	github.com/tiddly-data-converter/canon   => ../canon
	github.com/tiddly-data-converter/ingesta => ../ingesta
)
