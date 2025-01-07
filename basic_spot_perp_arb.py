from hyperliquid.utils import constants
import time

from example_utils import setup, print_json

class HypeSpotPerpArbitrage:
    """
    This strategy intends to buy spot and short perp to earn funding rate from hyperliquid.
    Under current version, we buy spot and short perp as a taker, using taker fee.
    In the future version, we plan to buy spot and short perp as a maker, using maker fee.
    This change wll earn us more profit.
    """
    def __init__(self):
        self.wallet, self.info, self.exchange = setup(constants.MAINNET_API_URL, skip_ws=True)
        
        self.coin = "HYPE"
        self.pair = self.coin + "/USDC"

        self.spot_order_result = None
        self.perp_order_result = None
        self.slippage = 0.01

        self.allocation = self.allocate_spot_perp_balance()
        self.spot_sz_decimals = self._get_spot_sz_decimals()
        self.perp_sz_decimals = self._get_perp_sz_decimals()

        self.is_spot_open = False
        self.is_perp_open = False

        self.perp_max_decimals = 6
        self.spot_max_decimals = 8
        
    # Function to get USDC(spot) and USDC(perp) balances
    def get_usdc_balances(self):
        """
        Get the USDC(spot) and USDC(perp) balances
        Return {
            'USDC_SPOT': 50.0,
            'USDC_PERP': 50.0
        }
        """
        spot_balance = self.get_spot_balance_by_token("USDC")
        perp_balance = self.get_withdrawable()
        total_balance = spot_balance + perp_balance
        
        return {
            'USDC_SPOT': spot_balance,
            'USDC_PERP': perp_balance,
            'TOTAL': total_balance
        }
    
    # Function to get balance by token_name
    def get_spot_balance_by_token(self, token_name):
        """
        Get the balance of token_name
        Return Type is float
        """
        data = self.info.spot_user_state(address=self.wallet)

        for balance in data['balances']:
            if balance['coin'] == token_name:
                try:
                    return float(balance['total'])
                except ValueError:
                    raise Exception(f"Invalid balance format for {token_name}.")
        raise Exception(f"Balance for {token_name} not found.")
    
    # Function to get withdrawable amount in USDC(perp)
    def get_withdrawable(self):
        """
        Get withdrawable in unit of USDC perp
        Return Type is float.
        """
        data = self.info.user_state(address=self.wallet)

        try:
            return float(data.get('withdrawable'))
        except (ValueError, TypeError):
            raise Exception("Invalid withdrawable amount format.")
        
    # Function to get funding rate by token_name
    def get_funding_rate_by_token(self, token_name):
        """
        # Sample context meta data
        data = [
            {
                "universe": [
                    {"szDecimals": 5, "name": "BTC", "maxLeverage": 50},
                    {"szDecimals": 4, "name": "ETH", "maxLeverage": 50}
                ]
            },
            [
                {
                    "funding": "0.0000125",
                    "openInterest": "8267.8146",
                    "prevDayPx": "93789.0",
                    "dayNtlVlm": "1795447570.10542965",
                    "premium": "0.00034473",
                    "oraclePx": "92536.0",
                    "markPx": "92568.0",
                    "midPx": "92570.5",
                    "impactPxs": [
                        "92567.9",
                        "92571.0"
                    ],
                    "dayBaseVlm": "19285.03292"
                },
                {
                    "funding": "0.0000125",
                    "openInterest": "187647.1638",
                    "prevDayPx": "3406.3",
                    "dayNtlVlm": "1400470812.74288845",
                    "premium": "0.00002991",
                    "oraclePx": "3342.9",
                    "markPx": "3343.0",
                    "midPx": "3343.05",
                    "impactPxs": [
                        "3343.0",
                        "3343.1"
                    ],
                    "dayBaseVlm": "415584.6913"
                },
            ]
        ]
        """
        # Get asset context meta data
        data = self.info.meta_and_asset_ctxs()

        # Create a mapping of token names to funding rates
        universe = data[0]['universe']
        token_map = {token['name']: index for index, token in enumerate(universe)}

        # Extract funding rates (second list in the data)
        funding_data = data[1]
        
        # Check if token exists in the mapping
        if token_name in token_map:
            index = token_map[token_name]
            if index < len(funding_data):
                return float(funding_data[index]['funding'])
            else:
                return f"Funding data for {token_name} not found."
        else:
            return f"Token {token_name} not found in universe."

    def _get_perp_sz_decimals(self):
        # Get the exchange's metadata and print it out
        meta = self.info.meta()
        # print(json.dumps(meta, indent=2))

        # create a szDecimals map
        perp_sz_decimals = {}
        for asset_info in meta["universe"]:
            perp_sz_decimals[asset_info["name"]] = asset_info["szDecimals"]

        return perp_sz_decimals
    
    def _get_spot_sz_decimals(self):
        # Get the exchange's metadata and print it out
        meta = self.info.spot_meta()
        # print(json.dumps(meta, indent=2))

        spot_sz_decimals = {}
        for asset_info in meta["tokens"]:
            spot_sz_decimals[asset_info["name"]] = asset_info["szDecimals"]
        
        return spot_sz_decimals

    def _round_perp_px_sz(self, px, sz):
        # If you use these directly, the exchange will return an error, so we round them.
        # First we check if price is greater than 100k in which case we just need to round to an integer
        if px > 100_000:
            px = round(px)
        # If not we round px to 5 significant figures and max_decimals - szDecimals decimals
        else:
            px = round(float(f"{px:.5g}"), self.perp_max_decimals - self.perp_sz_decimals[self.coin])

        # Truncate sz to the specified number of decimal places
        # Here we truncate sz because rounding sometimes rounds up a number, making sz*pz greater than original sz*pz.
        decimal_places = self.perp_sz_decimals[self.coin]
        factor = 10 ** decimal_places
        sz = int(sz * factor) / factor

        return px, sz

    def _round_spot_px_sz(self, px, sz):
        # If you use these directly, the exchange will return an error, so we round them.
        # First we check if price is greater than 100k in which case we just need to round to an integer
        if px > 100_000:
            px = round(px)
        # If not we round px to 5 significant figures and max_decimals - szDecimals decimals
        else:
            px = round(float(f"{px:.5g}"), self.spot_max_decimals - self.spot_sz_decimals[self.coin])

        # # Next we round sz based on the sz_decimals map we created
        # sz = round(sz, self.spot_sz_decimals[self.coin])
        
        # Truncate sz to the specified number of decimal places
        # # Here we truncate sz because rounding sometimes rounds up a number, making sz*pz greater than original sz*pz.
        decimal_places = self.spot_sz_decimals[self.coin]
        factor = 10 ** decimal_places
        sz = int(sz * factor) / factor

        return px, sz

    def place_spot_limit_order(self, is_buy=True):
        # Place limit order buy at the first ask price
        if is_buy:
            price = self._spot_bid_price_at_level(1)
            size = self.allocation / price
        else:
        # Place limit order sell at the first bid price
        # And sell all the spot balance
            price = self._spot_ask_price_at_level(1)
            size = self.get_spot_balance_by_token(self.coin)

        # Round the price and size to be compliant with hyperliquid's requirement
        price, size = self._round_spot_px_sz(price, size)

        # Using self.pair means this is a SPOT order.
        self.spot_order_result = self.exchange.order(self.pair, is_buy, size, price, {"limit": {"tif": "Gtc"}})

        # Query the order status by oid and Wait for spot order to be filled before continue
        # The Waiting part only works when we place limit order.
        if self.spot_order_result["status"] == "ok":
            status = self.spot_order_result["response"]["data"]["statuses"][0]
            if "resting" in status:
                oid = status["resting"]["oid"]
                order_status = self.exchange.info.query_order_by_oid(self.wallet, oid)
                print("Order status by oid:", order_status)

                # Wait until filled
                while True:
                    order_status = self.exchange.info.query_order_by_oid(self.wallet, oid)
                    if order_status['order']['status'] == 'filled':
                        break

                    if is_buy:
                        print("Waiting for spot buy order to be filled.")
                    else:
                        print("Waiting for spot sell order to be filled.")

        return self.spot_order_result
    
    def _spot_ask_price_at_level(self, level):
        data = self.info.l2_snapshot(self.pair)
        asks = data['levels'][1]  # Second list in 'levels' is asks
        return float(asks[level]['px'])
    
    def _perp_ask_price_at_level(self, level):
        data = self.info.l2_snapshot(self.coin)
        asks = data['levels'][1]  # Second list in 'levels' is asks
        return float(asks[level]['px'])

    def _spot_bid_price_at_level(self, level):
        data = self.info.l2_snapshot(self.pair)
        bids = data['levels'][0]  # First list in 'levels' is bids
        return float(bids[level]['px'])

    def _perp_bid_price_at_level(self, level):
        data = self.info.l2_snapshot(self.coin)
        bids = data['levels'][0]  # First list in 'levels' is bids
        return float(bids[level]['px'])
        
    def place_perp_limit_order(self, size, price, is_buy=False):
        self.perp_order_result = self.exchange.order(self.coin, is_buy, size, price, {"limit": {"tif": "Gtc"}})

        # print_json(self.perp_order_result)

        # # Query the order status by oid
        # if self.perp_order_result["status"] == "ok":
        #     status = self.perp_order_result["response"]["data"]["statuses"][0]
        #     if "resting" in status:
        #         oid = status["resting"]["oid"]
        #         order_status = self.info.query_order_by_oid(self.wallet, oid)
        #         print("Order status by oid:", order_status)

        #         # Wait until filled
        #         while True:
        #             order_status = self.exchange.info.query_order_by_oid(self.wallet, oid)
        #             if order_status['order']['status'] == 'filled':
        #                 break
        #             print("Waiting for perp short order to be filled.")
        return self.perp_order_result   

    def place_perp_market_order(self, is_buy=False):
        # Here the size means the units of coin rather than the units of USDC
        size = self.get_spot_balance_by_token(self.coin)
        # price = self._perp_ask_price_at_level(1)

        if not size > 0:
            print(f"No spot balance. Spot Buy May NOT SUCCEED.")
            return
        
        _, size = self._round_perp_px_sz(0.0, size)

        print(f"There are {size} {self.coin} in the balance.")
        print(f"We are going to open corresponding amount of short position.")

        self.perp_order_result = self.exchange.market_open(self.coin, is_buy, size, slippage=self.slippage)
        if self.perp_order_result["status"] == "ok":
            for status in self.perp_order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    print(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    print(f'Error: {status["error"]}')        

        return self.perp_order_result

    def close_positions(self):   
        # Sell all spot 
        print(f"We try to sell all {self.coin}.")
        coin_spot_balance = self.get_spot_balance_by_token(self.coin)
        if coin_spot_balance > 0:
            self.place_spot_limit_order(is_buy=False)
        else:
            print(f"No spot balance. Nothing to sell.")
            
        # Close short perp
        print(f"We try to close all {self.coin}.")
        order_result = self.exchange.market_close(self.coin)
        if order_result["status"] == "ok":
            for status in order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    print(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    print(f'Error: {status["error"]}')

    def allocate_spot_perp_balance(self):
        """
        Evenly allocate spot and perp usdc balance;
        In a word, rebalance the balance.
        Return the evenly allocated balance, which is half the total.
        """
        balances = self.get_usdc_balances()
        usdc_spot = balances['USDC_SPOT']
        usdc_perp = balances['USDC_PERP']
        total_usdc = balances['TOTAL']
        allocation = total_usdc / 2

        print(f"The current usdc_spot is {usdc_spot} and usdc_perp is {usdc_perp}.")

        # If usdc_perp > usdc_spot, transfer (usdc_perp - usdc_spot)/2 from perp to spot
        # If usdc_perp < usdc_spot, transfer (usdc_spot - usdc_perp)/2 from spot to perp
        if usdc_perp > usdc_spot:
            transfer_amount = (usdc_perp - usdc_spot) / 2
            transfer_result = self.exchange.usd_class_transfer(transfer_amount, False)
            print("Since usdc_perp > usdc_spot, transfer from perp to spot: ", transfer_result)
        else:
            transfer_amount = (usdc_spot - usdc_perp) / 2
            transfer_result = self.exchange.usd_class_transfer(transfer_amount, True)
            print("Since usdc_spot > usdc_perp, transfer from spot to perp: ", transfer_result)
        
        new_balances = self.get_usdc_balances()
        new_usdc_spot = new_balances['USDC_SPOT']
        new_usdc_perp = new_balances['USDC_PERP']

        if abs(new_usdc_perp - allocation) < 0.0001 and abs(new_usdc_spot - allocation) < 0.0001:
            print(f"The usdc_spot is {new_usdc_spot} and the usdc_perp is {new_usdc_perp}")
            print(f"Allocation complete and successful.")
        
        return allocation

    def get_position_value(self):
        """
        Extracts the position value from the provided data structure.

        Parameters:
        - data (dict): The input data containing position details.

        # Example usage:
        data = {
            "marginSummary": {
                "accountValue": "49.589238",
                "totalNtlPos": "50.26905",
                "totalRawUsd": "99.858288",
                "totalMarginUsed": "50.26905"
            },
            "crossMarginSummary": {
                "accountValue": "49.589238",
                "totalNtlPos": "50.26905",
                "totalRawUsd": "99.858288",
                "totalMarginUsed": "50.26905"
            },
            "crossMaintenanceMarginUsed": "8.378175",
            "withdrawable": "0.0",
            "assetPositions": [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": "HYPE",
                        "szi": "-1.95",
                        "leverage": {
                            "type": "cross",
                            "value": 1
                        },
                        "entryPx": "25.578",
                        "positionValue": "50.26905",
                        "unrealizedPnl": "-0.39195",
                        "returnOnEquity": "-0.00785832",
                        "liquidationPx": "43.89375297",
                        "marginUsed": "50.26905",
                        "maxLeverage": 3,
                        "cumFunding": {
                            "allTime": "-0.089456",
                            "sinceOpen": "-0.002625",
                            "sinceChange": "-0.002625"
                        }
                    }
                }
            ],
            "time": 1736219976887
        }

        Returns:
        - float: The value of position_value if found, otherwise None.
        """
        try:
            data = self.info.user_state(address=self.wallet)
            # Navigate through the structure to find the position_value
            position_value = data['assetPositions'][0]['position']['positionValue']
            return float(position_value)  # Convert the position value to float
        except (KeyError, IndexError) as e:
            print(f"Error extracting position_value: {e}")
            return None

    def run_strategy(self):
        while True:
            try:
                funding_rate = self.get_funding_rate_by_token(self.coin)
                
                # Only operates when funding_rate is positive
                if funding_rate > 0:

                    if not self.is_spot_open and not self.is_perp_open:
                        self.allocation = self.allocate_spot_perp_balance()
                        self.place_spot_limit_order(is_buy=True)
                        self.is_spot_open = True
                        self.place_perp_market_order(is_buy=False)
                        self.is_perp_open = True
                    else:
                        print(f"Orders are open and funding rate {funding_rate} is positive.")
    
                else:

                    if self.is_spot_open and self.is_perp_open:
                        print(f"Funding rate is {funding_rate}, negative. We close positions.")
                        self.close_positions()
                        self.is_spot_open = False
                        self.is_perp_open = False
                
                # Check funding_rate every hour
                time.sleep(60 * 60)

            except Exception as e:
                print(f"Strategy errs: {e}")
                time.sleep(60)
            

if __name__ == "__main__":
    arbitrage = HypeSpotPerpArbitrage()
    arbitrage.run_strategy()