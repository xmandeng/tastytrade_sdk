// -----------------------------------------------------------------------
// Candlestick
// -----------------------------------------------------------------------
from(bucket: "tastytrade")
  |> range(start: -3d)  // Adjust time range as needed
  |> filter(fn: (r) => r._measurement == "CandleEvent")
  |> filter(fn: (r) => r.eventSymbol == "SPX{=5m}")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["_time", "open", "high", "low", "close", "volume"])
  |> sort(columns: ["_time"], desc: false)

// -----------------------------------------------------------------------
// Priod Day Range
// -----------------------------------------------------------------------

import "date"
import "experimental"

// Define time range (last 3 days)
startTime = experimental.addDuration(
    d: -4d,
    to: date.truncate(t: now(), unit: 1d)
)
stopTime = now()

// Get original series with daily aggregation
original = from(bucket: "tastytrade")
    |> range(start: startTime, stop: stopTime)
    |> filter(fn: (r) =>
        r._measurement == "CandleEvent" and
        r.eventSymbol == "SPX{=d}" and  // Changed to daily timeframe
        (r._field == "prevHigh" or
         r._field == "prevLow" or
         r._field == "prevClose")        // Added prevClose
    )
    |> map(fn: (r) => ({
        r with
        _field: if r._field == "prevHigh" then "day_High"
                else if r._field == "prevLow" then "day_Low"
                else if r._field == "prevClose" then "day_Close"
                else r._field
    }))
    |> aggregateWindow(
        every: 1d,
        fn: last,
        createEmpty: false
    )
    |> keep(columns: ["_time", "_value", "_field", "tradeDateUTC"])

// Generate market open data using parsed date
market_open = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 14h30m, to: r._time)
    }))

// Generate market close data
market_close = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 21h, to: r._time)
    }))

// Generate gap points
gap_points = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 21h30m, to: r._time)
    }))
    |> drop(columns: ["_value"])

// Combine all data
union(tables: [market_open, market_close, gap_points])
    |> group(columns: ["_field"])
    |> sort(columns: ["_time"])

// -----------------------------------------------------------------------
// 15min Open
// -----------------------------------------------------------------------
import "date"
import "experimental"

// Define time range (last 3 days)
startTime = experimental.addDuration(
    d: -4d,
    to: date.truncate(t: now(), unit: 1d)
)
stopTime = now()

// Get original series with daily aggregation
original = from(bucket: "tastytrade")
    |> range(start: startTime, stop: stopTime)
    |> filter(fn: (r) =>
        r._measurement == "CandleEvent" and
        r.eventSymbol == "SPX{=15m}" and
        r.tradeTime == "09:45" and
        (r._field == "prevHigh" or r._field == "prevLow")
    )
    |> map(fn: (r) => ({
        r with
        _field: if r._field == "prevHigh" then "open_15mHi"
                else if r._field == "prevLow" then "open_15mLo"
                else r._field
    }))
    |> aggregateWindow(
        every: 1d,
        fn: last,
        createEmpty: false
    )
    |> keep(columns: ["_time", "_value", "_field", "tradeDateUTC"])

// Generate market open data using parsed date
market_open = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 14h30m, to: r._time)
    }))

// Generate market close data
market_close = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 21h, to: r._time)
    }))

// Generate gap points
gap_points = original
    |> map(fn: (r) => ({
        r with
        _time: date.truncate(t: time(v: r.tradeDateUTC), unit: 1d)
    }))
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(d: 21h30m, to: r._time)
    }))
    |> drop(columns: ["_value"])

// Combine all data
union(tables: [market_open, market_close, gap_points])
    |> group(columns: ["_field"])
    |> sort(columns: ["_time"])

// -----------------------------------------------------------------------
// 5min Open
// -----------------------------------------------------------------------

// Legacy Open_5min Query
import "date"
import "experimental"

// Define time range (last 14 days)
startTime = experimental.addDuration(
    d: -3d,
    to: date.truncate(t: now(), unit: 1d)
)
stopTime = now()

// Fetch data with the new fields
base_data = from(bucket: "tastytrade")
    |> range(start: startTime, stop: stopTime)
    |> filter(fn: (r) =>
        r._measurement == "CandleEvent" and
        r.eventSymbol == "SPX{=5m}" and
        r.tradeTime == "09:35" and
        (r._field == "prevHigh" or r._field == "prevLow")
    )
    |> map(fn: (r) => ({
        r with
        _field: if r._field == "prevHigh" then "open_5mHi"
                else if r._field == "prevLow" then "open_5mLo"
                else r._field
    }))
    |> aggregateWindow(
        every: 1d,
        fn: last,
        createEmpty: false
    )
    |> keep(columns: ["_time", "_value", "_field"])

// Generate Market Open Data (9:30 AM EDT = 14:30 UTC)
open_data = base_data
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(
            d: 14h30m,
            to: experimental.addDuration(
                d: -24h,
                to: date.truncate(t: r._time, unit: 1d)
            )
        )
    }))

// Generate Market Close Data (4:00 PM EDT = 21:00 UTC)
close_data = base_data
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(
            d: 21h,
            to: experimental.addDuration(
                d: -24h,
                to: date.truncate(t: r._time, unit: 1d)
            )
        )
    }))

// Generate Gap Data (4:30 PM EDT = 21:30 UTC)
gap_data = base_data
    |> map(fn: (r) => ({
        r with
        _time: experimental.addDuration(
            d: 21h30m,
            to: experimental.addDuration(
                d: -24h,
                to: date.truncate(t: r._time, unit: 1d)
            )
        )
    }))
    |> drop(columns: ["_value"])

// Combine all data and ensure proper grouping
union(tables: [open_data, close_data, gap_data])
    |> group(columns: ["_field"])
    |> sort(columns: ["_time"])
