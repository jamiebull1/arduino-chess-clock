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
int lcd_key     = 0;
int adc_key_in  = 0;
#define btnRIGHT  0
#define btnUP     1
#define btnDOWN   2
#define btnLEFT   3
#define btnSELECT 4
#define btnNONE   5
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

// Code below here is mine
// Initialise some global parameters
boolean isUsingMenu = false;  // whether we are in the time-setting menu
boolean isGameOver = false;
String playIndicator = "  --  ";  // for the centre of the display when no player is active

class Player {
  // Represents a player.
  public:
    int minutes;              // number of minutes allowed  
    boolean isActive;         // is the player's clock counting down?
    String menuText;          // text for the time-setting menu
    long secondsRun;          // seconds run while the player was active

    void IncrementMinutes();   
    void DecrementMinutes();   
    int SecondsRemaining();
};

void Player::IncrementMinutes() {
  if (this->minutes < 99) {
    this->minutes += 1;
  }
};

void Player::DecrementMinutes() {
  if (this->minutes > 1) {
    this->minutes -= 1;
  }
};

int Player::SecondsRemaining() {
  // number of seconds remaining on the player's clock
  int minsAllowed = this->minutes;
  int secondsRunSoFar = this->secondsRun;
  return minsAllowed * 60 - secondsRunSoFar;
};

String timeString(long seconds){
  // Convert seconds to an MM:SS display.
  int runSecs = seconds % 60;
  int runMins = seconds / 60;

  // number of seconds for the MM:SS display
  String displaySeconds;
  if (runSecs < 10) {
    displaySeconds = "0" + String(runSecs);
  } else {
    displaySeconds = String(runSecs);    
  }
  // number of minutes for the MM:SS display
  String displayMinutes;
  if (runMins < 10) {
    displayMinutes = "0" + String(runMins);
  } else {
    displayMinutes = String(runMins);    
  }
  // Create and return the formatted string
  String displayString = displayMinutes + ":" + displaySeconds;
  return displayString;
}

// initialise the players
Player p0 = {0, true, "", 0};  // dummy player, active when player clocks are not counting down
Player p1 = {5, false, "Player1 mins: ", 0};
Player p2 = {5, false, "Player2 mins: ", 0};

// set a pointer to the first player to be shown in the time-setting menu
Player* menuPlayer = &p1;

void updateCounters(){
  // Update the counters for each player
  if (p0.isActive) {
    p0.secondsRun += millis()/1000 - (
      p0.secondsRun + 
      p1.secondsRun + 
      p2.secondsRun
      );
    }
  if (p1.isActive) {
    p1.secondsRun += millis()/1000 - (
      p0.secondsRun + 
      p1.secondsRun + 
      p2.secondsRun
      );
    }
  if (p2.isActive) {
    p2.secondsRun += millis()/1000 - (
      p0.secondsRun + 
      p1.secondsRun + 
      p2.secondsRun
      );
    }
}

void setup()
{
 lcd.begin(16, 2);  
 lcd.setCursor(0,0);
 lcd.print("P1 ChessClock P2");
}

// Main loop
void loop()
{
 updateCounters();  // do this every loop
 lcd_key = read_LCD_buttons();  
 if (isUsingMenu) {
   switch (lcd_key)               
   {
     case btnUP:
       {
        // increase minutes
        menuPlayer->IncrementMinutes();        
        delay(250);        
        break;
       }  
     case btnDOWN:
       {
        // decrease minutes        
        menuPlayer->DecrementMinutes();        
        delay(250);        
        break;
       }  
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
 } else {
   switch (lcd_key)               
   {
     case btnLEFT:
       {
        // player 1
        playIndicator = "  <-  ";
        p0.isActive = false;
        p1.isActive = true;
        p2.isActive = false;
        lcd.setCursor(5,1);            
        lcd.print(playIndicator);
        break;
       }
     case btnRIGHT:
       {
        // player 2
        playIndicator = "  ->  ";
        p0.isActive = false;
        p1.isActive = false;
        p2.isActive = true;
        lcd.setCursor(5,1);        
        lcd.print(playIndicator);
        break;
       }
     case btnUP:
       {
        // pause the timers
        p0.isActive = true;
        p1.isActive = false;
        p2.isActive = false;
        playIndicator = "  --  ";
        break;
       }
     case btnDOWN:
       {
        // not used      
        break;
       }
     case btnSELECT:
       {
        if (isGameOver){
          // select button resets the game
          p0.secondsRun += (p1.secondsRun + p2.secondsRun);
          p1.secondsRun = 0;
          p2.secondsRun = 0;
          p0.isActive = true;
          p1.isActive = false;
          p2.isActive = false;
          playIndicator = "  --  ";
          isGameOver = false;
          delay(500);
          break;
        } else {
          // activate the menu
          isUsingMenu = true;   
          p0.isActive = true;
          p1.isActive = false;
          p2.isActive = false;
          delay(500);  // delay required otherwise the button fires repeatedly
          break;
        }
       }
     case btnNONE:
       {
        if (isGameOver) {
          // do nothing and wait for btnSELECT to reset the game
          break;  
        } else {
          // check if either player is out of time
          if (p1.SecondsRemaining() <= 0) {  // player 1 lost
            lcd.setCursor(0,0);
            lcd.print("   Game Over!   ");
            lcd.setCursor(0,1);
            lcd.print(" Player 1 loses ");
            isGameOver = true;
            break;
          } else if (p2.SecondsRemaining() <= 0) {  // player 2 lost
            lcd.setCursor(0,0);
            lcd.print("   Game Over!   ");
            lcd.setCursor(0,1);
            lcd.print(" Player 2 loses ");
            isGameOver = true;
            break;
          } else {
            // update timer display
            lcd.setCursor(0,0);
            lcd.print("P1 ChessClock P2");
            lcd.setCursor(0,1);
            lcd.print(timeString(p1.SecondsRemaining()));      
            lcd.setCursor(5,1);            
            lcd.print(playIndicator);        
            lcd.setCursor(11,1);
            lcd.print(timeString(p2.SecondsRemaining()));
          }
          break;
        }       
       }
     }
   }
}
