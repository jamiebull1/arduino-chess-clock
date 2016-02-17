// Chess clock using the LiquidCrystal library
#include <LiquidCrystal.h>

/*******************************************************

This program uses the LCD panel and keypad to create a
chess timer.

The main display, which shows the active player and the
two countdown timers, is as follows:

P1 ChessClock P2
MM:SS  --  MM:SS

The menu display, used to set the minutes available for
each player, is:

      MENU      
Player1 mins: MM      

Jamie Bull, February 2016

********************************************************/
//================================================================
// This code is from a sample library on how to use the LCD keypad
// http://www.dfrobot.com/wiki/index.php?title=Arduino_LCD_KeyPad_Shield_%28SKU:_DFR0009%29

// select the pins used on the LCD panel
LiquidCrystal lcd(8, 9, 4, 5, 6, 7);
// define some values used by the panel and buttons
int lcdKey      = 0;
int adc_key_in  = 0;

enum Button 
{
    btnRIGHT,
    btnUP,
    btnDOWN,
    btnLEFT,
    btnSELECT,
    btnNONE
};

// read the buttons
int read_LCD_buttons()
{
    adc_key_in = analogRead(0);      // read the value from the sensor 
    // buttons when read are centered at these values: 0, 144, 329, 504, 741
    // we add approx 50 to those values and check to see if we are close
    
    // We make this the 1st option for speed reasons since it will be the most likely result
    if (adc_key_in > 1000) return btnNONE; 
    if (adc_key_in < 50)   return btnRIGHT;  
    if (adc_key_in < 250)  return btnUP; 
    if (adc_key_in < 450)  return btnDOWN; 
    if (adc_key_in < 650)  return btnLEFT; 
    if (adc_key_in < 850)  return btnSELECT;
    
    return btnNONE;  // when all others fail, return this...
}
//================================================================

// Initialise some global parameters
bool isUsingMenu = false;  // whether we are in the time-setting menu
bool isGameOver = false;

class Player 
{
    // Represents a player.
    public:
        int minutes;              // number of minutes allowed  
        String menuText;          // text for the time-setting menu
        String playIndicator;     // indicator for when active
        long secondsRun;          // seconds run while the player was active
    
        void IncrementMinutes() 
        {
            minutes = min(minutes + 1, 99);
            delay(250);        
        }
        void DecrementMinutes()
        {
            minutes = max(minutes - 1, 1);
            delay(250);        
        }
        int SecondsRemaining() 
        {
            // number of seconds remaining on the player's clock
            int minsAllowed = minutes;
            int secondsRunSoFar = secondsRun;
            return minsAllowed * 60 - secondsRunSoFar;
        }
        void UpdateCounter(Player p0, Player p1, Player p2)
        {
            secondsRun += millis()/1000 - (p0.secondsRun + p1.secondsRun + p2.secondsRun);
        }
};

// initialise the players
Player p0 = {0, "",               "  --  ", 0};  // dummy player, active when player clocks are not counting down
Player p1 = {5, "Player1 mins: ", "  <-  ", 0};
Player p2 = {5, "Player2 mins: ", "  ->  ", 0};

// set a pointer to the first player to be shown in the time-setting menu
Player* menuPlayer = &p1;
// set the active player pointer to the player to start with
Player* activePlayer = &p0;

void setup()
{
    lcd.begin(16, 2);  
}

// Main loop
void loop()
{
    activePlayer->UpdateCounter(p0, p1, p2);;  // do this every loop
    lcdKey = read_LCD_buttons();  
    if (isUsingMenu) 
    {
        updateMenuScreen();
    } else {
        updateTimerScreen();
    }
}

void resetGame()
// reset game to starting state
{
    p0.secondsRun += (p1.secondsRun + p2.secondsRun);
    p1.secondsRun = 0;
    p2.secondsRun = 0;
    activePlayer = &p0;
    isGameOver = false;
}

void updateTimerScreen()
{
    switch (lcdKey)               
    {
    case btnLEFT: { activePlayer = &p1; break; }  // set player 1 active
    
    case btnRIGHT: { activePlayer = &p2; break; } // set player 2 active
    
    case btnUP: { activePlayer = &p0; break; }    // pause the timers
    
    case btnDOWN: { break; }                      // not used
    
    case btnSELECT: // to activate menu (or reset if game is over)
        {
        if (isGameOver)
        {
            resetGame();
        } else {
            // activate the menu
            isUsingMenu = true;   
            activePlayer = &p0;
        }
        delay(500);  // delay required otherwise the button fires repeatedly
        break;
        }
    case btnNONE:  // update timer if no button pressed
        {
        if (isGameOver) {
            // do nothing and wait for btnSELECT to reset the game
        } else {
            // check if either player is out of time
            int loser = getLoserNumber();
            
            lcd.setCursor(0,0);
            if (loser > 0) {
                lcd.print("   Game Over!   ");
                lcd.setCursor(0,1);
                lcd.print(" Player " + String(loser) + " loses ");
                isGameOver = true;
            } else {
                // update timer display
                lcd.print("P1 ChessClock P2");
                lcd.setCursor(0,1);
                lcd.print(timeString(p1.SecondsRemaining()));      
                lcd.setCursor(5,1);            
                lcd.print(activePlayer->playIndicator);        
                lcd.setCursor(11,1);
                lcd.print(timeString(p2.SecondsRemaining()));
            }
        }
        }
    }
}

void updateMenuScreen()
{
    switch (lcdKey)                
    {
    case btnUP: 
        { menuPlayer->IncrementMinutes(); break; } // increase minutes
    case btnDOWN:
        { menuPlayer->DecrementMinutes(); break; } // decrease minutes
    case btnLEFT:
        {
        // set pointer to player 1 as player to change time for
        menuPlayer = &p1;
        break;
        }  
    case btnRIGHT:
        {
        // set pointer to player 2 as player to change time for
        menuPlayer = &p2;
        break;
        }  
    case btnSELECT:
        {
        // return to timer screen
        isUsingMenu = false;
        delay(500);  // delay required otherwise the button fires repeatedly
        break;       
        }  
    case btnNONE:
        {
        // update menu display
        lcd.setCursor(0,0);
        lcd.print("      MENU      ");
        lcd.setCursor(0,1);
        String playerMins;
        if (menuPlayer->minutes < 10) {
            playerMins = " " + String(menuPlayer->minutes);
        } else {
            playerMins = String(menuPlayer->minutes);
        }
        lcd.print(menuPlayer->menuText + playerMins);
        break;       
        }
    }
}
    
int getLoserNumber()
// return the number of the losing player, or 0 if both have time remaining
{
    if (p1.SecondsRemaining() <= 0)
        {
        return 1;
    } else if (p2.SecondsRemaining() <= 0)
        {
        return 2;
    }
    return 0;
}

String timeString(long seconds)
// Convert seconds to an MM:SS display.
{
    int runMins = seconds / 60;
    int runSecs = seconds % 60;
  
    return pad(runMins) + ":" + pad(runSecs);
};

String pad(int toPad)
// Zero-pad to ensure two chars in the string for mins/secs
{
    if (toPad < 10) {
        return "0" + String(toPad);
    } else {
        return String(toPad);
    }
};


